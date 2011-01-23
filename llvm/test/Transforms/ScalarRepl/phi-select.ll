; RUN: opt %s -scalarrepl -S | FileCheck %s
; Test promotion of allocas that have phis and select users.
target datalayout = "e-p:64:64:64-i1:8:8-i8:8:8-i16:16:16-i32:32:32-i64:64:64-f32:32:32-f64:64:64-v64:64:64-v128:128:128-a0:0:64-s0:64:64-f80:128:128-n8:16:32:64"
target triple = "x86_64-apple-darwin10.2"

%struct.X = type { i32 }
%PairTy = type {i32, i32}

; CHECK: @test1
; CHECK: %a.0 = alloca i32
; CHECK: %b.0 = alloca i32
define i32 @test1(i32 %x) nounwind readnone ssp {
entry:
  %a = alloca %struct.X, align 8                  ; <%struct.X*> [#uses=2]
  %b = alloca %struct.X, align 8                  ; <%struct.X*> [#uses=2]
  %0 = getelementptr inbounds %struct.X* %a, i64 0, i32 0 ; <i32*> [#uses=1]
  store i32 1, i32* %0, align 8
  %1 = getelementptr inbounds %struct.X* %b, i64 0, i32 0 ; <i32*> [#uses=1]
  store i32 2, i32* %1, align 8
  %2 = icmp eq i32 %x, 0                          ; <i1> [#uses=1]
  %p.0 = select i1 %2, %struct.X* %b, %struct.X* %a ; <%struct.X*> [#uses=1]
  %3 = getelementptr inbounds %struct.X* %p.0, i64 0, i32 0 ; <i32*> [#uses=1]
  %4 = load i32* %3, align 8                      ; <i32> [#uses=1]
  ret i32 %4
}

; CHECK: @test2
; CHECK: %A.0 = alloca i32
; CHECK: %A.1 = alloca i32
define i32 @test2(i1 %c) {
entry:
  %A = alloca {i32, i32}
  %B = getelementptr {i32, i32}* %A, i32 0, i32 0
  store i32 1, i32* %B
  br i1 %c, label %T, label %F
T:
  %C = getelementptr {i32, i32}* %A, i32 0, i32 1
  store i32 2, i32* %B
  br label %F
F:
  %X = phi i32* [%B, %entry], [%C, %T]
  %Q = load i32* %X
  ret i32 %Q
}

; CHECK: @test3
; CHECK: %A.0 = alloca i32
; CHECK: %A.1 = alloca i32
; rdar://8904039
define i32 @test3(i1 %c) {
entry:
  %A = alloca {i32, i32}
  %B = getelementptr {i32, i32}* %A, i32 0, i32 0
  store i32 1, i32* %B
  %C = getelementptr {i32, i32}* %A, i32 0, i32 1
  store i32 2, i32* %B
  
  %X = select i1 %c, i32* %B, i32* %C
  %Q = load i32* %X
  ret i32 %Q
}

;; We can't scalarize this, a use of the select is not an element access.
define i64 @test4(i1 %c) {
entry:
  %A = alloca %PairTy
  ; CHECK: @test4
  ; CHECK: %A = alloca %PairTy
  %B = getelementptr {i32, i32}* %A, i32 0, i32 0
  store i32 1, i32* %B
  %C = getelementptr {i32, i32}* %A, i32 0, i32 1
  store i32 2, i32* %B
  
  %X = select i1 %c, i32* %B, i32* %C
  %Y = bitcast i32* %X to i64*
  %Q = load i64* %Y
  ret i64 %Q
}
