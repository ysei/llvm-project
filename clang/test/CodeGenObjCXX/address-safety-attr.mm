// RUN: %clang_cc1 -emit-llvm -o - %s | FileCheck -check-prefix=WITHOUT %s
// RUN: %clang_cc1 -emit-llvm -o - %s -fsanitize=address | FileCheck -check-prefix=ASAN %s

@interface MyClass
+ (int) addressSafety:(int*)a;
@end

@implementation MyClass

// WITHOUT:  +[MyClass load]{{.*}}#0
// ASAN: +[MyClass load]{{.*}}#0
+(void) load { }

// WITHOUT:  +[MyClass addressSafety:]{{.*}}#0
// ASAN:  +[MyClass addressSafety:]{{.*}}#0
+ (int) addressSafety:(int*)a { return *a; }

@end

// WITHOUT: attributes #0 = { nounwind{{.*}} }
// ASAN: attributes #0 = { address_safety nounwind{{.*}} }
