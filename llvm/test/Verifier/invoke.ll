; RUN: not llvm-as < %s -o /dev/null |& FileCheck %s

; PR1042
define i32 @foo() {
; CHECK: The unwind destination does not have a landingpad instruction
	%A = invoke i32 @foo( )
			to label %L unwind label %L		; <i32> [#uses=1]
L:		; preds = %0, %0
	ret i32 %A
}

; PR1042
define i32 @bar() {
	br i1 false, label %L1, label %L2
L1:		; preds = %0
	%A = invoke i32 @bar( )
			to label %L unwind label %L		; <i32> [#uses=1]
L2:		; preds = %0
	br label %L
L:		; preds = %L2, %L1, %L1
; CHECK: The unwind destination does not have a landingpad instruction
; CHECK: Instruction does not dominate all uses
	ret i32 %A
}


declare i32 @__gxx_personality_v0(...)
declare void @llvm.donothing()
declare void @llvm.trap()
declare i8 @llvm.expect.i8(i8,i8)
declare i32 @fn(i8 (i8, i8)*)

define void @f1() {
entry:
; OK
  invoke void @llvm.donothing()
  to label %cont unwind label %cont

cont:
  %0 = landingpad { i8*, i32 } personality i8* bitcast (i32 (...)* @__gxx_personality_v0 to i8*)
          filter [0 x i8*] zeroinitializer
  ret void
}

define i8 @f2() {
entry:
; CHECK: Cannot invoke an intrinsinc other than donothing
  invoke void @llvm.trap()
  to label %cont unwind label %lpad

cont:
  ret i8 3

lpad:
  %0 = landingpad { i8*, i32 } personality i8* bitcast (i32 (...)* @__gxx_personality_v0 to i8*)
          filter [0 x i8*] zeroinitializer
  ret i8 2
}

define i32 @f3() {
entry:
; CHECK: Cannot take the address of an intrinsic
  %call = call i32 @fn(i8 (i8, i8)* @llvm.expect.i8)
  ret i32 %call
}
