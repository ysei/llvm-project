// RUN: %clang -ccc-host-triple mips64el-unknown-linux -ccc-clang-archs mips64el -O3 -S -mabi=n64 -o - -emit-llvm %s | FileCheck %s

typedef struct {
  double d;
  long double ld;
} S0;

// Insert padding to ensure arugments of type S0 are aligned to 16-byte boundaries.

// CHECK: define void @foo1(i32 %a0, i64, double %a1.coerce0, i64 %a1.coerce1, i64 %a1.coerce2, i64 %a1.coerce3, double %a2.coerce0, i64 %a2.coerce1, i64 %a2.coerce2, i64 %a2.coerce3, i32 %b, i64, double %a3.coerce0, i64 %a3.coerce1, i64 %a3.coerce2, i64 %a3.coerce3)
// CHECK: tail call void @foo2(i32 1, i32 2, i32 %a0, i64 undef, double %a1.coerce0, i64 %a1.coerce1, i64 %a1.coerce2, i64 %a1.coerce3, double %a2.coerce0, i64 %a2.coerce1, i64 %a2.coerce2, i64 %a2.coerce3, i32 3, i64 undef, double %a3.coerce0, i64 %a3.coerce1, i64 %a3.coerce2, i64 %a3.coerce3)
// CHECK: declare void @foo2(i32, i32, i32, i64, double, i64, i64, i64, double, i64, i64, i64, i32, i64, double, i64, i64, i64)

extern void foo2(int, int, int, S0, S0, int, S0);

void foo1(int a0, S0 a1, S0 a2, int b, S0 a3) {
  foo2(1, 2, a0, a1, a2, 3, a3);
}

