//===-- Symbols.cpp ---------------------------------------------*- C++ -*-===//
//
//                     The LLVM Compiler Infrastructure
//
// This file is distributed under the University of Illinois Open Source
// License. See LICENSE.TXT for details.
//
//===----------------------------------------------------------------------===//

#include "lldb/Host/Symbols.h"

// C Includes
#include <dirent.h>
#include "llvm/Support/MachO.h"

// C++ Includes
// Other libraries and framework includes
#include <CoreFoundation/CoreFoundation.h>

// Project includes
#include "lldb/Core/ArchSpec.h"
#include "lldb/Core/DataBuffer.h"
#include "lldb/Core/DataExtractor.h"
#include "lldb/Core/Module.h"
#include "lldb/Core/Timer.h"
#include "lldb/Core/UUID.h"
#include "lldb/Host/Endian.h"
#include "lldb/Host/Host.h"
#include "lldb/Utility/CleanUp.h"
#include "Host/macosx/cfcpp/CFCBundle.h"
#include "Host/macosx/cfcpp/CFCReleaser.h"
#include "Host/macosx/cfcpp/CFCString.h"
#include "mach/machine.h"


using namespace lldb;
using namespace lldb_private;
using namespace llvm::MachO;

#if !defined (__arm__) // No DebugSymbols on the iOS devices
extern "C" {

CFURLRef DBGCopyFullDSYMURLForUUID (CFUUIDRef uuid, CFURLRef exec_url);
CFDictionaryRef DBGCopyDSYMPropertyLists (CFURLRef dsym_url);

}
#endif

static bool
SkinnyMachOFileContainsArchAndUUID
(
    const FileSpec &file_spec,
    const ArchSpec *arch,
    const lldb_private::UUID *uuid,   // the UUID we are looking for
    off_t file_offset,
    DataExtractor& data,
    uint32_t data_offset,
    const uint32_t magic
)
{
    assert(magic == HeaderMagic32 || magic == HeaderMagic32Swapped || magic == HeaderMagic64 || magic == HeaderMagic64Swapped);
    if (magic == HeaderMagic32 || magic == HeaderMagic64)
        data.SetByteOrder (lldb::endian::InlHostByteOrder());
    else if (lldb::endian::InlHostByteOrder() == eByteOrderBig)
        data.SetByteOrder (eByteOrderLittle);
    else
        data.SetByteOrder (eByteOrderBig);

    uint32_t i;
    const uint32_t cputype      = data.GetU32(&data_offset);    // cpu specifier
    const uint32_t cpusubtype   = data.GetU32(&data_offset);    // machine specifier
    data_offset+=4; // Skip mach file type
    const uint32_t ncmds        = data.GetU32(&data_offset);    // number of load commands
    const uint32_t sizeofcmds   = data.GetU32(&data_offset);    // the size of all the load commands
    data_offset+=4; // Skip flags

    // Check the architecture if we have a valid arch pointer
    if (arch)
    {
        ArchSpec file_arch(eArchTypeMachO, cputype, cpusubtype);

        if (file_arch != *arch)
            return false;
    }

    // The file exists, and if a valid arch pointer was passed in we know
    // if already matches, so we can return if we aren't looking for a specific
    // UUID
    if (uuid == NULL)
        return true;

    if (magic == HeaderMagic64Swapped || magic == HeaderMagic64)
        data_offset += 4;   // Skip reserved field for in mach_header_64

    // Make sure we have enough data for all the load commands
    if (magic == HeaderMagic64Swapped || magic == HeaderMagic64)
    {
        if (data.GetByteSize() < sizeof(struct mach_header_64) + sizeofcmds)
        {
            DataBufferSP data_buffer_sp (file_spec.ReadFileContents (file_offset, sizeof(struct mach_header_64) + sizeofcmds));
            data.SetData (data_buffer_sp);
        }
    }
    else
    {
        if (data.GetByteSize() < sizeof(struct mach_header) + sizeofcmds)
        {
            DataBufferSP data_buffer_sp (file_spec.ReadFileContents (file_offset, sizeof(struct mach_header) + sizeofcmds));
            data.SetData (data_buffer_sp);
        }
    }

    for (i=0; i<ncmds; i++)
    {
        const uint32_t cmd_offset = data_offset;    // Save this data_offset in case parsing of the segment goes awry!
        uint32_t cmd        = data.GetU32(&data_offset);
        uint32_t cmd_size   = data.GetU32(&data_offset);
        if (cmd == LoadCommandUUID)
        {
            lldb_private::UUID file_uuid (data.GetData(&data_offset, 16), 16);
            if (file_uuid == *uuid)
                return true;

            // Emit some warning messages since the UUIDs do not match!
            char path_buf[PATH_MAX];
            path_buf[0] = '\0';
            const char *path = file_spec.GetPath(path_buf, PATH_MAX) ? path_buf
                                                                     : file_spec.GetFilename().AsCString();
            Host::SystemLog (Host::eSystemLogWarning, 
                             "warning: UUID mismatch detected between binary and:\n\t'%s'\n", 
                             path);
            return false;
        }
        data_offset = cmd_offset + cmd_size;
    }
    return false;
}

bool
UniversalMachOFileContainsArchAndUUID
(
    const FileSpec &file_spec,
    const ArchSpec *arch,
    const lldb_private::UUID *uuid,
    off_t file_offset,
    DataExtractor& data,
    uint32_t data_offset,
    const uint32_t magic
)
{
    assert(magic == UniversalMagic || magic == UniversalMagicSwapped);

    // Universal mach-o files always have their headers encoded as BIG endian
    data.SetByteOrder(eByteOrderBig);

    uint32_t i;
    const uint32_t nfat_arch = data.GetU32(&data_offset);   // number of structs that follow
    const uint32_t fat_header_and_arch_size = sizeof(struct fat_header) + nfat_arch * sizeof(struct fat_arch);
    if (data.GetByteSize() < fat_header_and_arch_size)
    {
        DataBufferSP data_buffer_sp (file_spec.ReadFileContents (file_offset, fat_header_and_arch_size));
        data.SetData (data_buffer_sp);
    }

    for (i=0; i<nfat_arch; i++)
    {
        cpu_type_t      arch_cputype        = data.GetU32(&data_offset);    // cpu specifier (int)
        cpu_subtype_t   arch_cpusubtype     = data.GetU32(&data_offset);    // machine specifier (int)
        uint32_t        arch_offset         = data.GetU32(&data_offset);    // file offset to this object file
    //  uint32_t        arch_size           = data.GetU32(&data_offset);    // size of this object file
    //  uint32_t        arch_align          = data.GetU32(&data_offset);    // alignment as a power of 2
        data_offset += 8;   // Skip size and align as we don't need those
        // Only process this slice if the cpu type/subtype matches
        if (arch)
        {
            ArchSpec fat_arch(eArchTypeMachO, arch_cputype, arch_cpusubtype);
            if (fat_arch != *arch)
                continue;
        }

        // Create a buffer with only the arch slice date in it
        DataExtractor arch_data;
        DataBufferSP data_buffer_sp (file_spec.ReadFileContents (file_offset + arch_offset, 0x1000));
        arch_data.SetData(data_buffer_sp);
        uint32_t arch_data_offset = 0;
        uint32_t arch_magic = arch_data.GetU32(&arch_data_offset);

        switch (arch_magic)
        {
        case HeaderMagic32:
        case HeaderMagic32Swapped:
        case HeaderMagic64:
        case HeaderMagic64Swapped:
            if (SkinnyMachOFileContainsArchAndUUID (file_spec, arch, uuid, file_offset + arch_offset, arch_data, arch_data_offset, arch_magic))
                return true;
            break;
        }
    }
    return false;
}

static bool
FileAtPathContainsArchAndUUID
(
    const FileSpec &file_spec,
    const ArchSpec *arch,
    const lldb_private::UUID *uuid
)
{
    DataExtractor data;
    off_t file_offset = 0;
    DataBufferSP data_buffer_sp (file_spec.ReadFileContents (file_offset, 0x1000));

    if (data_buffer_sp && data_buffer_sp->GetByteSize() > 0)
    {
        data.SetData(data_buffer_sp);

        uint32_t data_offset = 0;
        uint32_t magic = data.GetU32(&data_offset);

        switch (magic)
        {
        // 32 bit mach-o file
        case HeaderMagic32:
        case HeaderMagic32Swapped:
        case HeaderMagic64:
        case HeaderMagic64Swapped:
            return SkinnyMachOFileContainsArchAndUUID (file_spec, arch, uuid, file_offset, data, data_offset, magic);

        // fat mach-o file
        case UniversalMagic:
        case UniversalMagicSwapped:
            return UniversalMachOFileContainsArchAndUUID (file_spec, arch, uuid, file_offset, data, data_offset, magic);

        default:
            break;
        }
    }
    return false;
}

static FileSpec
LocateDSYMMachFileInDSYMBundle
(
    const FileSpec& dsym_bundle_fspec,
    const lldb_private::UUID *uuid,
    const ArchSpec *arch)
{
    char path[PATH_MAX];

    FileSpec dsym_fspec;

    if (dsym_bundle_fspec.GetPath(path, sizeof(path)))
    {
        ::strncat (path, "/Contents/Resources/DWARF", sizeof(path) - strlen(path) - 1);

        lldb_utility::CleanUp <DIR *, int> dirp (opendir(path), NULL, closedir);
        if (dirp.is_valid())
        {
            dsym_fspec.GetDirectory().SetCString(path);
            struct dirent* dp;
            while ((dp = readdir(dirp.get())) != NULL)
            {
                // Only search directories
                if (dp->d_type == DT_DIR || dp->d_type == DT_UNKNOWN)
                {
                    if (dp->d_namlen == 1 && dp->d_name[0] == '.')
                        continue;

                    if (dp->d_namlen == 2 && dp->d_name[0] == '.' && dp->d_name[1] == '.')
                        continue;
                }

                if (dp->d_type == DT_REG || dp->d_type == DT_UNKNOWN)
                {
                    dsym_fspec.GetFilename().SetCString(dp->d_name);
                    if (FileAtPathContainsArchAndUUID (dsym_fspec, arch, uuid))
                        return dsym_fspec;
                }
            }
        }
    }
    dsym_fspec.Clear();
    return dsym_fspec;
}

static int
LocateMacOSXFilesUsingDebugSymbols
(
    const ModuleSpec &module_spec,
    FileSpec *out_exec_fspec,   // If non-NULL, try and find the executable
    FileSpec *out_dsym_fspec    // If non-NULL try and find the debug symbol file
)
{
    int items_found = 0;

    if (out_exec_fspec)
        out_exec_fspec->Clear();

    if (out_dsym_fspec)
        out_dsym_fspec->Clear();

#if !defined (__arm__) // No DebugSymbols on the iOS devices

    const UUID *uuid = module_spec.GetUUIDPtr();
    const ArchSpec *arch = module_spec.GetArchitecturePtr();

    if (uuid && uuid->IsValid())
    {
        // Try and locate the dSYM file using DebugSymbols first
        const UInt8 *module_uuid = (const UInt8 *)uuid->GetBytes();
        if (module_uuid != NULL)
        {
            CFCReleaser<CFUUIDRef> module_uuid_ref(::CFUUIDCreateWithBytes (NULL,
                                                                            module_uuid[0],
                                                                            module_uuid[1],
                                                                            module_uuid[2],
                                                                            module_uuid[3],
                                                                            module_uuid[4],
                                                                            module_uuid[5],
                                                                            module_uuid[6],
                                                                            module_uuid[7],
                                                                            module_uuid[8],
                                                                            module_uuid[9],
                                                                            module_uuid[10],
                                                                            module_uuid[11],
                                                                            module_uuid[12],
                                                                            module_uuid[13],
                                                                            module_uuid[14],
                                                                            module_uuid[15]));

            if (module_uuid_ref.get())
            {
                CFCReleaser<CFURLRef> exec_url;
                const FileSpec *exec_fspec = module_spec.GetFileSpecPtr();
                if (exec_fspec)
                {
                    char exec_cf_path[PATH_MAX];
                    if (exec_fspec->GetPath(exec_cf_path, sizeof(exec_cf_path)))
                        exec_url.reset(::CFURLCreateFromFileSystemRepresentation (NULL,
                                                                                  (const UInt8 *)exec_cf_path,
                                                                                  strlen(exec_cf_path),
                                                                                  FALSE));
                }

                CFCReleaser<CFURLRef> dsym_url (::DBGCopyFullDSYMURLForUUID(module_uuid_ref.get(), exec_url.get()));
                char path[PATH_MAX];

                if (dsym_url.get())
                {
                    if (out_dsym_fspec)
                    {
                        if (::CFURLGetFileSystemRepresentation (dsym_url.get(), true, (UInt8*)path, sizeof(path)-1))
                        {
                            out_dsym_fspec->SetFile(path, false);

                            if (out_dsym_fspec->GetFileType () == FileSpec::eFileTypeDirectory)
                            {
                                *out_dsym_fspec = LocateDSYMMachFileInDSYMBundle (*out_dsym_fspec, uuid, arch);
                                if (*out_dsym_fspec)
                                    ++items_found;
                            }
                            else
                            {
                                ++items_found;
                            }
                        }
                    }

                    if (out_exec_fspec)
                    {
                        CFCReleaser<CFDictionaryRef> dict(::DBGCopyDSYMPropertyLists (dsym_url.get()));
                        bool success = false;
                        if (dict.get())
                        {
                            char uuid_cstr_buf[64];
                            const char *uuid_cstr = uuid->GetAsCString (uuid_cstr_buf, sizeof(uuid_cstr_buf));
                            CFCString uuid_cfstr (uuid_cstr);
                            CFDictionaryRef uuid_dict = static_cast<CFDictionaryRef>(::CFDictionaryGetValue (dict.get(), uuid_cfstr.get()));
                            if (uuid_dict)
                            {
                                CFStringRef exec_cf_path = static_cast<CFStringRef>(::CFDictionaryGetValue (uuid_dict, CFSTR("DBGSymbolRichExecutable")));
                                if (exec_cf_path && ::CFStringGetFileSystemRepresentation (exec_cf_path, path, sizeof(path)))
                                {
                                    ++items_found;
                                    out_exec_fspec->SetFile(path, path[0] == '~');
                                    if (out_exec_fspec->Exists())
                                        success = true;
                                }
                            }
                        }

                        if (!success)
                        {
                            // No dictionary, check near the dSYM bundle for an executable that matches...
                            if (::CFURLGetFileSystemRepresentation (dsym_url.get(), true, (UInt8*)path, sizeof(path)-1))
                            {
                                char *dsym_extension_pos = ::strstr (path, ".dSYM");
                                if (dsym_extension_pos)
                                {
                                    *dsym_extension_pos = '\0';
                                    FileSpec file_spec (path, true);
                                    switch (file_spec.GetFileType())
                                    {
                                        case FileSpec::eFileTypeDirectory:  // Bundle directory?
                                            {
                                                CFCBundle bundle (path);
                                                CFCReleaser<CFURLRef> bundle_exe_url (bundle.CopyExecutableURL ());
                                                if (bundle_exe_url.get())
                                                {
                                                    if (::CFURLGetFileSystemRepresentation (bundle_exe_url.get(), true, (UInt8*)path, sizeof(path)-1))
                                                    {
                                                        FileSpec bundle_exe_file_spec (path, true);
                                                        
                                                        if (FileAtPathContainsArchAndUUID (bundle_exe_file_spec, arch, uuid))
                                                        {
                                                            ++items_found;
                                                            *out_exec_fspec = bundle_exe_file_spec;
                                                        }
                                                    }
                                                }
                                            }
                                            break;
                                            
                                        case FileSpec::eFileTypePipe:       // Forget pipes
                                        case FileSpec::eFileTypeSocket:     // We can't process socket files
                                        case FileSpec::eFileTypeInvalid:    // File doesn't exist...
                                            break;

                                        case FileSpec::eFileTypeUnknown:
                                        case FileSpec::eFileTypeRegular:
                                        case FileSpec::eFileTypeSymbolicLink:
                                        case FileSpec::eFileTypeOther:
                                            if (FileAtPathContainsArchAndUUID (file_spec, arch, uuid))
                                            {
                                                ++items_found;
                                                *out_exec_fspec = file_spec;
                                            }
                                            break;
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }
#endif // #if !defined (__arm__)

    return items_found;
}

static bool
LocateDSYMInVincinityOfExecutable (const ModuleSpec &module_spec, FileSpec &dsym_fspec)
{
    const FileSpec *exec_fspec = module_spec.GetFileSpecPtr();
    if (exec_fspec)
    {
        char path[PATH_MAX];
        if (exec_fspec->GetPath(path, sizeof(path)))
        {
            // Make sure the module isn't already just a dSYM file...
            if (strcasestr(path, ".dSYM/Contents/Resources/DWARF") == NULL)
            {
                size_t obj_file_path_length = strlen(path);
                strncat(path, ".dSYM/Contents/Resources/DWARF/", sizeof(path));
                strncat(path, exec_fspec->GetFilename().AsCString(), sizeof(path));

                dsym_fspec.SetFile(path, false);

                if (dsym_fspec.Exists() && FileAtPathContainsArchAndUUID (dsym_fspec, module_spec.GetArchitecturePtr(), module_spec.GetUUIDPtr()))
                {
                    return true;
                }
                else
                {
                    path[obj_file_path_length] = '\0';

                    char *last_dot = strrchr(path, '.');
                    while (last_dot != NULL && last_dot[0])
                    {
                        char *next_slash = strchr(last_dot, '/');
                        if (next_slash != NULL)
                        {
                            *next_slash = '\0';
                            strncat(path, ".dSYM/Contents/Resources/DWARF/", sizeof(path));
                            strncat(path, exec_fspec->GetFilename().AsCString(), sizeof(path));
                            dsym_fspec.SetFile(path, false);
                            if (dsym_fspec.Exists() && FileAtPathContainsArchAndUUID (dsym_fspec, module_spec.GetArchitecturePtr(), module_spec.GetUUIDPtr()))
                                return true;
                            else
                            {
                                *last_dot = '\0';
                                char *prev_slash = strrchr(path, '/');
                                if (prev_slash != NULL)
                                    *prev_slash = '\0';
                                else
                                    break;
                            }
                        }
                        else
                        {
                            break;
                        }
                    }
                }
            }
        }
    }
    dsym_fspec.Clear();
    return false;
}

FileSpec
Symbols::LocateExecutableObjectFile (const ModuleSpec &module_spec)
{
    const FileSpec *exec_fspec = module_spec.GetFileSpecPtr();
    const ArchSpec *arch = module_spec.GetArchitecturePtr();
    const UUID *uuid = module_spec.GetUUIDPtr();
    Timer scoped_timer (__PRETTY_FUNCTION__,
                        "LocateExecutableObjectFile (file = %s, arch = %s, uuid = %p)",
                        exec_fspec ? exec_fspec->GetFilename().AsCString ("<NULL>") : "<NULL>",
                        arch ? arch->GetArchitectureName() : "<NULL>",
                        uuid);

    FileSpec objfile_fspec;
    if (exec_fspec && FileAtPathContainsArchAndUUID (exec_fspec, arch, uuid))
        objfile_fspec = exec_fspec;
    else
        LocateMacOSXFilesUsingDebugSymbols (module_spec, &objfile_fspec, NULL);
    return objfile_fspec;
}

FileSpec
Symbols::LocateExecutableSymbolFile (const ModuleSpec &module_spec)
{
    const FileSpec *exec_fspec = module_spec.GetFileSpecPtr();
    const ArchSpec *arch = module_spec.GetArchitecturePtr();
    const UUID *uuid = module_spec.GetUUIDPtr();

    Timer scoped_timer (__PRETTY_FUNCTION__,
                        "LocateExecutableSymbolFile (file = %s, arch = %s, uuid = %p)",
                        exec_fspec ? exec_fspec->GetFilename().AsCString ("<NULL>") : "<NULL>",
                        arch ? arch->GetArchitectureName() : "<NULL>",
                        uuid);

    FileSpec symbol_fspec;
    // First try and find the dSYM in the same directory as the executable or in
    // an appropriate parent directory
    if (LocateDSYMInVincinityOfExecutable (module_spec, symbol_fspec) == false)
    {
        // We failed to easily find the dSYM above, so use DebugSymbols
        LocateMacOSXFilesUsingDebugSymbols (module_spec, NULL, &symbol_fspec);
    }
    return symbol_fspec;
}
