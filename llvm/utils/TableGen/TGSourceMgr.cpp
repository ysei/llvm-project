//===- TGSourceMgr.cpp - Manager for Source Buffers & Diagnostics ---------===//
//
//                     The LLVM Compiler Infrastructure
//
// This file is distributed under the University of Illinois Open Source
// License. See LICENSE.TXT for details.
//
//===----------------------------------------------------------------------===//
//
// This file implements the TGSourceMgr class.
//
//===----------------------------------------------------------------------===//

#include "TGSourceMgr.h"
#include "llvm/Support/MemoryBuffer.h"
#include "llvm/Support/raw_ostream.h"
using namespace llvm;

TGSourceMgr::~TGSourceMgr() {
  while (!Buffers.empty()) {
    delete Buffers.back().Buffer;
    Buffers.pop_back();
  }
}

/// FindBufferContainingLoc - Return the ID of the buffer containing the
/// specified location, returning -1 if not found.
int TGSourceMgr::FindBufferContainingLoc(TGLocTy Loc) const {
  for (unsigned i = 0, e = Buffers.size(); i != e; ++i)
    if (Loc >= Buffers[i].Buffer->getBufferStart() &&
        Loc <  Buffers[i].Buffer->getBufferEnd())
      return i;
  return -1;
}

/// FindLineNumber - Find the line number for the specified location in the
/// specified file.  This is not a fast method.
unsigned TGSourceMgr::FindLineNumber(TGLocTy Loc, int BufferID) const {
  if (BufferID == -1) BufferID = FindBufferContainingLoc(Loc);
  assert(BufferID != -1 && "Invalid Location!");
  
  MemoryBuffer *Buff = getBufferInfo(BufferID).Buffer;
  
  // Count the number of \n's between the start of the file and the specified
  // location.
  unsigned LineNo = 1;
  
  const char *Ptr = Buff->getBufferStart();

  for (; Ptr != Loc; ++Ptr)
    if (*Ptr == '\n') ++LineNo;
  return LineNo;
}

void TGSourceMgr::PrintIncludeStack(TGLocTy IncludeLoc) const {
  if (IncludeLoc == TGLocTy()) return;  // Top of stack.
  
  int CurBuf = FindBufferContainingLoc(IncludeLoc);
  assert(CurBuf != -1 && "Invalid or unspecified location!");

  PrintIncludeStack(getBufferInfo(CurBuf).IncludeLoc);
  
  errs() << "Included from "
         << getBufferInfo(CurBuf).Buffer->getBufferIdentifier()
         << ":" << FindLineNumber(IncludeLoc, CurBuf) << ":\n";
}


void TGSourceMgr::PrintError(TGLocTy ErrorLoc, const std::string &Msg) const {
  raw_ostream &OS = errs();
  
  // First thing to do: find the current buffer containing the specified
  // location.
  int CurBuf = FindBufferContainingLoc(ErrorLoc);
  assert(CurBuf != -1 && "Invalid or unspecified location!");
  
  PrintIncludeStack(getBufferInfo(CurBuf).IncludeLoc);
  
  MemoryBuffer *CurMB = getBufferInfo(CurBuf).Buffer;
  
  
  OS << "Parsing " << CurMB->getBufferIdentifier() << ":"
     << FindLineNumber(ErrorLoc, CurBuf) << ": ";
  
  OS << Msg << "\n";
  assert(ErrorLoc && "Location not specified!");
  
  // Scan backward to find the start of the line.
  const char *LineStart = ErrorLoc;
  while (LineStart != CurMB->getBufferStart() && 
         LineStart[-1] != '\n' && LineStart[-1] != '\r')
    --LineStart;
  // Get the end of the line.
  const char *LineEnd = ErrorLoc;
  while (LineEnd != CurMB->getBufferEnd() && 
         LineEnd[0] != '\n' && LineEnd[0] != '\r')
    ++LineEnd;
  // Print out the line.
  OS << std::string(LineStart, LineEnd) << "\n";
  // Print out spaces before the carat.
  for (const char *Pos = LineStart; Pos != ErrorLoc; ++Pos)
    OS << (*Pos == '\t' ? '\t' : ' ');
  OS << "^\n";
}
