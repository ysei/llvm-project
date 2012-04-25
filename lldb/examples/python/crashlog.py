#!/usr/bin/python

#----------------------------------------------------------------------
# Be sure to add the python path that points to the LLDB shared library.
#
# To use this in the embedded python interpreter using "lldb":
#
#   cd /path/containing/crashlog.py
#   lldb
#   (lldb) script import crashlog
#   "crashlog" command installed, type "crashlog --help" for detailed help
#   (lldb) crashlog ~/Library/Logs/DiagnosticReports/a.crash
#
# The benefit of running the crashlog command inside lldb in the 
# embedded python interpreter is when the command completes, there 
# will be a target with all of the files loaded at the locations
# described in the crash log. Only the files that have stack frames
# in the backtrace will be loaded unless the "--load-all" option
# has been specified. This allows users to explore the program in the
# state it was in right at crash time. 
#
# On MacOSX csh, tcsh:
#   ( setenv PYTHONPATH /path/to/LLDB.framework/Resources/Python ; ./crashlog.py ~/Library/Logs/DiagnosticReports/a.crash )
#
# On MacOSX sh, bash:
#   PYTHONPATH=/path/to/LLDB.framework/Resources/Python ./crashlog.py ~/Library/Logs/DiagnosticReports/a.crash
#----------------------------------------------------------------------

import lldb
import commands
import optparse
import os
import plistlib
import pprint # pp = pprint.PrettyPrinter(indent=4); pp.pprint(command_args)
import re
import shlex
import sys
import time
import uuid
import lldb.utils.symbolication 

PARSE_MODE_NORMAL = 0
PARSE_MODE_THREAD = 1
PARSE_MODE_IMAGES = 2
PARSE_MODE_THREGS = 3
PARSE_MODE_SYSTEM = 4

class CrashLog(lldb.utils.symbolication.Symbolicator):
    """Class that does parses darwin crash logs"""
    thread_state_regex = re.compile('^Thread ([0-9]+) crashed with')
    thread_regex = re.compile('^Thread ([0-9]+)([^:]*):(.*)')
    frame_regex = re.compile('^([0-9]+) +([^ ]+) *\t(0x[0-9a-fA-F]+) +(.*)')
    image_regex_uuid = re.compile('(0x[0-9a-fA-F]+)[- ]+(0x[0-9a-fA-F]+) +[+]?([^ ]+) +([^<]+)<([-0-9a-fA-F]+)> (.*)');
    image_regex_no_uuid = re.compile('(0x[0-9a-fA-F]+)[- ]+(0x[0-9a-fA-F]+) +[+]?([^ ]+) +([^/]+)/(.*)');
    empty_line_regex = re.compile('^$')
        
    class Thread:
        """Class that represents a thread in a darwin crash log"""
        def __init__(self, index):
            self.index = index
            self.frames = list()
            self.registers = dict()
            self.reason = None
            self.queue = None
        
        def dump(self, prefix):
            print "%sThread[%u] %s" % (prefix, self.index, self.reason)
            if self.frames:
                print "%s  Frames:" % (prefix)
                for frame in self.frames:
                    frame.dump(prefix + '    ')
            if self.registers:
                print "%s  Registers:" % (prefix)
                for reg in self.registers.keys():
                    print "%s    %-5s = %#16.16x" % (prefix, reg, self.registers[reg])
        
        def did_crash(self):
            return self.reason != None
        
        def __str__(self):
            s = "Thread[%u]" % self.index
            if self.reason:
                s += ' %s' % self.reason
            return s
        
    
    class Frame:
        """Class that represents a stack frame in a thread in a darwin crash log"""
        def __init__(self, index, pc, description):
            self.pc = pc
            self.description = description
            self.index = index
        
        def __str__(self):
            if self.description:
                return "[%3u] 0x%16.16x %s" % (self.index, self.pc, self.description)
            else:
                return "[%3u] 0x%16.16x" % (self.index, self.pc)        
    
    class DarwinImage(lldb.utils.symbolication.Image):
        """Class that represents a binary images in a darwin crash log"""
        dsymForUUIDBinary = os.path.expanduser('~rc/bin/dsymForUUID')
        if not os.path.exists(dsymForUUIDBinary):
            dsymForUUIDBinary = commands.getoutput('which dsymForUUID')
            
        dwarfdump_uuid_regex = re.compile('UUID: ([-0-9a-fA-F]+) \(([^\(]+)\) .*')
        
        def __init__(self, text_addr_lo, text_addr_hi, identifier, version, uuid, path):
            lldb.utils.symbolication.Image.__init__(self, path, uuid);
            self.add_section (lldb.utils.symbolication.Section(text_addr_lo, text_addr_hi, "__TEXT"))
            self.identifier = identifier
            self.version = version
        
        def locate_module_and_debug_symbols(self):
            if self.resolved_path:
                # Don't load a module twice...
                return True
            print 'Getting symbols for %s %s...' % (self.uuid, self.path),
            if os.path.exists(self.dsymForUUIDBinary):
                dsym_for_uuid_command = '%s %s' % (self.dsymForUUIDBinary, self.uuid)
                s = commands.getoutput(dsym_for_uuid_command)
                if s:
                    plist_root = plistlib.readPlistFromString (s)
                    if plist_root:
                        plist = plist_root[self.uuid]
                        if plist:
                            if 'DBGArchitecture' in plist:
                                self.arch = plist['DBGArchitecture']
                            if 'DBGDSYMPath' in plist:
                                self.symfile = os.path.realpath(plist['DBGDSYMPath'])
                            if 'DBGSymbolRichExecutable' in plist:
                                self.resolved_path = os.path.expanduser (plist['DBGSymbolRichExecutable'])
            if not self.resolved_path and os.path.exists(self.path):
                dwarfdump_cmd_output = commands.getoutput('dwarfdump --uuid "%s"' % self.path)
                self_uuid = uuid.UUID(self.uuid)
                for line in dwarfdump_cmd_output.splitlines():
                    match = self.dwarfdump_uuid_regex.search (line)
                    if match:
                        dwarf_uuid_str = match.group(1)
                        dwarf_uuid = uuid.UUID(dwarf_uuid_str)
                        if self_uuid == dwarf_uuid:
                            self.resolved_path = self.path
                            self.arch = match.group(2)
                            break;
                if not self.resolved_path:
                    print "error: file %s '%s' doesn't match the UUID in the installed file" % (self.uuid, self.path)
                    return False
            if (self.resolved_path and os.path.exists(self.resolved_path)) or (self.path and os.path.exists(self.path)):
                print 'ok'
                # if self.resolved_path:
                #     print '  exe = "%s"' % self.resolved_path 
                # if self.symfile:
                #     print ' dsym = "%s"' % self.symfile
                return True
            return False
        
    
        
    def __init__(self, path):
        """CrashLog constructor that take a path to a darwin crash log file"""
        lldb.utils.symbolication.Symbolicator.__init__(self);
        self.path = os.path.expanduser(path);
        self.info_lines = list()
        self.system_profile = list()
        self.threads = list()
        self.idents = list() # A list of the required identifiers for doing all stack backtraces
        self.crashed_thread_idx = -1
        self.version = -1
        self.error = None
        # With possible initial component of ~ or ~user replaced by that user's home directory.
        try:
            f = open(self.path)
        except IOError:
            self.error = 'error: cannot open "%s"' % self.path
            return

        self.file_lines = f.read().splitlines()
        parse_mode = PARSE_MODE_NORMAL
        thread = None
        for line in self.file_lines:
            # print line
            line_len = len(line)
            if line_len == 0:
                if thread:
                    if parse_mode == PARSE_MODE_THREAD:
                        if thread.index == self.crashed_thread_idx:
                            thread.reason = ''
                            if self.thread_exception:
                                thread.reason += self.thread_exception
                            if self.thread_exception_data:
                                thread.reason += " (%s)" % self.thread_exception_data                                
                        self.threads.append(thread)
                    thread = None
                else:
                    # only append an extra empty line if the previous line 
                    # in the info_lines wasn't empty
                    if len(self.info_lines) > 0 and len(self.info_lines[-1]):
                        self.info_lines.append(line)
                parse_mode = PARSE_MODE_NORMAL
                # print 'PARSE_MODE_NORMAL'
            elif parse_mode == PARSE_MODE_NORMAL:
                if line.startswith ('Process:'):
                    (self.process_name, pid_with_brackets) = line[8:].strip().split()
                    self.process_id = pid_with_brackets.strip('[]')
                elif line.startswith ('Path:'):
                    self.process_path = line[5:].strip()
                elif line.startswith ('Identifier:'):
                    self.process_identifier = line[11:].strip()
                elif line.startswith ('Version:'):
                    (self.process_version, compatability_version) = line[8:].strip().split()
                    self.process_compatability_version = compatability_version.strip('()')
                elif line.startswith ('Parent Process:'):
                    (self.parent_process_name, pid_with_brackets) = line[15:].strip().split()
                    self.parent_process_id = pid_with_brackets.strip('[]') 
                elif line.startswith ('Exception Type:'):
                    self.thread_exception = line[15:].strip()
                    continue
                elif line.startswith ('Exception Codes:'):
                    self.thread_exception_data = line[16:].strip()
                    continue
                elif line.startswith ('Crashed Thread:'):
                    self.crashed_thread_idx = int(line[15:].strip().split()[0])
                    continue
                elif line.startswith ('Report Version:'):
                    self.version = int(line[15:].strip())
                    continue
                elif line.startswith ('System Profile:'):
                    parse_mode = PARSE_MODE_SYSTEM
                    continue
                elif (line.startswith ('Interval Since Last Report:') or
                      line.startswith ('Crashes Since Last Report:') or
                      line.startswith ('Per-App Interval Since Last Report:') or
                      line.startswith ('Per-App Crashes Since Last Report:') or
                      line.startswith ('Sleep/Wake UUID:') or
                      line.startswith ('Anonymous UUID:')):
                    # ignore these
                    continue  
                elif line.startswith ('Thread'):
                    thread_state_match = self.thread_state_regex.search (line)
                    if thread_state_match:
                        thread_state_match = self.thread_regex.search (line)
                        thread_idx = int(thread_state_match.group(1))
                        parse_mode = PARSE_MODE_THREGS
                        thread = self.threads[thread_idx]
                    else:
                        thread_match = self.thread_regex.search (line)
                        if thread_match:
                            # print 'PARSE_MODE_THREAD'
                            parse_mode = PARSE_MODE_THREAD
                            thread_idx = int(thread_match.group(1))
                            thread = CrashLog.Thread(thread_idx)
                    continue
                elif line.startswith ('Binary Images:'):
                    parse_mode = PARSE_MODE_IMAGES
                    continue
                self.info_lines.append(line.strip())
            elif parse_mode == PARSE_MODE_THREAD:
                frame_match = self.frame_regex.search(line)
                if frame_match:
                    ident = frame_match.group(2)
                    if not ident in self.idents:
                        self.idents.append(ident)
                    thread.frames.append (CrashLog.Frame(int(frame_match.group(1)), int(frame_match.group(3), 0), frame_match.group(4)))
                else:
                    print 'error: frame regex failed for line: "%s"' % line
            elif parse_mode == PARSE_MODE_IMAGES:
                image_match = self.image_regex_uuid.search (line)
                if image_match:
                    image = CrashLog.DarwinImage (int(image_match.group(1),0), 
                                                  int(image_match.group(2),0), 
                                                  image_match.group(3).strip(), 
                                                  image_match.group(4).strip(), 
                                                  image_match.group(5), 
                                                  image_match.group(6))
                    self.images.append (image)
                else:
                    image_match = self.image_regex_no_uuid.search (line)
                    if image_match:
                        image = CrashLog.DarwinImage (int(image_match.group(1),0), 
                                                      int(image_match.group(2),0), 
                                                      image_match.group(3).strip(), 
                                                      image_match.group(4).strip(), 
                                                      None,
                                                      image_match.group(5))
                        self.images.append (image)
                    else:
                        print "error: image regex failed for: %s" % line

            elif parse_mode == PARSE_MODE_THREGS:
                stripped_line = line.strip()
                reg_values = stripped_line.split('  ')
                for reg_value in reg_values:
                    (reg, value) = reg_value.split(': ')
                    thread.registers[reg.strip()] = int(value, 0)
            elif parse_mode == PARSE_MODE_SYSTEM:
                self.system_profile.append(line)
        f.close()
        
    def dump(self):
        print "Crash Log File: %s" % (self.path)
        print "\nThreads:"
        for thread in self.threads:
            thread.dump('  ')
        print "\nImages:"
        for image in self.images:
            image.dump('  ')
    
    def find_image_with_identifier(self, identifier):
        for image in self.images:
            if image.identifier == identifier:
                return image
        return None
    
    def create_target(self):
        #print 'crashlog.create_target()...'
        target = lldb.utils.symbolication.Symbolicator.create_target(self)
        if target:
            return target
        # We weren't able to open the main executable as, but we can still symbolicate
        print 'crashlog.create_target()...2'
        if self.idents:
            for ident in self.idents:
                image = self.find_image_with_identifier (ident)
                if image:
                    target = image.create_target ()
                    if target:
                        return target # success
        print 'crashlog.create_target()...3'
        for image in self.images:
            target = image.create_target ()
            if target:
                return target # success
        print 'crashlog.create_target()...4'
        print 'error: unable to locate any executables from the crash log'
        return None


def usage():
    print "Usage: lldb-symbolicate.py [-n name] executable-image"
    sys.exit(0)

def Symbolicate(debugger, command, result, dict):
    try:
        SymbolicateCrashLog (shlex.split(command))
    except:
        result.PutCString ("error: python exception %s" % sys.exc_info()[0])
                
def SymbolicateCrashLog(command_args):
    usage = "usage: %prog [options] <FILE> [FILE ...]"
    description='''Symbolicate one or more darwin crash log files to provide source file and line information,
inlined stack frames back to the concrete functions, and disassemble the location of the crash
for the first frame of the crashed thread.
If this script is imported into the LLDB command interpreter, a "crashlog" command will be added to the interpreter
for use at the LLDB command line. After a crash log has been parsed and symbolicated, a target will have been
created that has all of the shared libraries loaded at the load addresses found in the crash log file. This allows
you to explore the program as if it were stopped at the locations described in the crash log and functions can 
be disassembled and lookups can be performed using the addresses found in the crash log.'''
    parser = optparse.OptionParser(description=description, prog='crashlog.py',usage=usage)
    parser.add_option('--platform', type='string', metavar='platform', dest='platform', help='specify one platform by name')
    parser.add_option('-v', '--verbose', action='store_true', dest='verbose', help='display verbose debug info', default=False)
    parser.add_option('--no-images', action='store_false', dest='show_images', help='don\'t show images in stack frames', default=True)
    parser.add_option('-a', '--load-all', action='store_true', dest='load_all_images', help='load all executable images, not just the images found in the crashed stack frames', default=False)
    parser.add_option('--image-list', action='store_true', dest='dump_image_list', help='show image list', default=False)
    parser.add_option('-g', '--debug-delay', type='int', dest='debug_delay', metavar='NSEC', help='pause for NSEC seconds for debugger', default=0)
    parser.add_option('-c', '--crashed-only', action='store_true', dest='crashed_only', help='only symbolicate the crashed thread', default=False)
    parser.add_option('-d', '--disasm-depth', type='int', dest='disassemble_depth', help='set the depth in stack frames that should be disassembled (default is 1)', default=1)
    parser.add_option('-D', '--disasm-all', action='store_true', dest='disassemble_all_threads', help='enabled disassembly of frames on all threads (not just the crashed thread)', default=False)
    parser.add_option('-B', '--disasm-before', type='int', dest='disassemble_before', help='the number of instructions to disassemble before the frame PC', default=4)
    parser.add_option('-A', '--disasm-after', type='int', dest='disassemble_after', help='the number of instructions to disassemble after the frame PC', default=4)
    loaded_addresses = False
    try:
        (options, args) = parser.parse_args(command_args)
    except:
        return
        
    if options.verbose:
        print 'command_args = %s' % command_args
        print 'options', options
        print 'args', args
        
    if options.debug_delay > 0:
        print "Waiting %u seconds for debugger to attach..." % options.debug_delay
        time.sleep(options.debug_delay)
    error = lldb.SBError()
    if args:
        for crash_log_file in args:
            crash_log = CrashLog(crash_log_file)
            
            #pp = pprint.PrettyPrinter(indent=4); pp.pprint(args)
            if crash_log.error:
                print crash_log.error
                return
            if options.verbose:
                crash_log.dump()
            if not crash_log.images:
                print 'error: no images in crash log'
                return

            target = crash_log.create_target ()
            if not target:
                return
            exe_module = target.GetModuleAtIndex(0)
            images_to_load = list()
            loaded_images = list()
            if options.load_all_images:
                # --load-all option was specified, load everything up
                for image in crash_log.images:
                    images_to_load.append(image)
            else:
                # Only load the images found in stack frames for the crashed threads
                for ident in crash_log.idents:
                    images = crash_log.find_images_with_identifier (ident)
                    if images:
                        for image in images:
                            images_to_load.append(image)
                    else:
                        print 'error: can\'t find image for identifier "%s"' % ident
            
            for image in images_to_load:
                if image in loaded_images:
                    print "warning: skipping %s loaded at %#16.16x duplicate entry (probably commpage)" % (image.path, image.text_addr_lo)
                else:
                    err = image.add_module (target)
                    if err:
                        print err
                    else:
                        #print 'loaded %s' % image
                        loaded_images.append(image)
            
            for thread in crash_log.threads:
                this_thread_crashed = thread.did_crash()
                if options.crashed_only and this_thread_crashed == False:
                    continue
                print "%s" % thread
                #prev_frame_index = -1
                for frame_idx, frame in enumerate(thread.frames):
                    disassemble = (this_thread_crashed or options.disassemble_all_threads) and frame_idx < options.disassemble_depth;
                    symbolicated_frame_addresses = crash_log.symbolicate (frame.pc)
                    if symbolicated_frame_addresses:
                        symbolicated_frame_address_idx = 0
                        for symbolicated_frame_address in symbolicated_frame_addresses:
                            print '[%3u] %s' % (frame_idx, symbolicated_frame_address)
                            
                            if symbolicated_frame_address_idx == 0:
                                if disassemble:
                                    instructions = symbolicated_frame_address.get_instructions()
                                    if instructions:
                                        print
                                        lldb.utils.symbolication.disassemble_instructions (target, 
                                                                                           instructions, 
                                                                                           frame.pc, 
                                                                                           options.disassemble_before, 
                                                                                           options.disassemble_after, frame.index > 0)
                                        print
                            symbolicated_frame_address_idx += 1
                    else:
                        print frame
                print                

            if options.dump_image_list:
                print "Binary Images:"
                for image in crash_log.images:
                    print image

if __name__ == '__main__':
    # Create a new debugger instance
    lldb.debugger = lldb.SBDebugger.Create()
    SymbolicateCrashLog (sys.argv[1:])
elif lldb.debugger:
    lldb.debugger.HandleCommand('command script add -f lldb.macosx.crashlog.Symbolicate crashlog')
    print '"crashlog" command installed, type "crashlog --help" for detailed help'

