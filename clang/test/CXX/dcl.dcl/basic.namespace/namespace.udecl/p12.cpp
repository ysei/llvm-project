// RUN: clang -fsyntax-only -verify %s

// C++03 [namespace.udecl]p12:
//   When a using-declaration brings names from a base class into a
//   derived class scope, member functions in the derived class
//   override and/or hide member functions with the same name and
//   parameter types in a base class (rather than conflicting).

// PR5727
// This just shouldn't crash.
namespace test0 {
  template<typename> struct RefPtr { };
  template<typename> struct PtrHash {
    static void f() { }
  };
  template<typename T> struct PtrHash<RefPtr<T> > : PtrHash<T*> {
    using PtrHash<T*>::f;
    static void f() { f(); }
  };
}

// Simple hiding.
namespace test1 {
  template <unsigned n> struct Opaque {};
  struct Base {
    Opaque<0> foo(Opaque<0>);
    Opaque<0> foo(Opaque<1>);
    Opaque<0> foo(Opaque<2>);
  };

  // using before decls
  struct Test0 : Base {
    using Base::foo;
    Opaque<1> foo(Opaque<1>);
    Opaque<1> foo(Opaque<3>);

    void test0() { Opaque<0> _ = foo(Opaque<0>()); }
    void test1() { Opaque<1> _ = foo(Opaque<1>()); }
    void test2() { Opaque<0> _ = foo(Opaque<2>()); }
    void test3() { Opaque<1> _ = foo(Opaque<3>()); }
  };

  // using after decls
  struct Test1 : Base {
    Opaque<1> foo(Opaque<1>);
    Opaque<1> foo(Opaque<3>);
    using Base::foo;

    void test0() { Opaque<0> _ = foo(Opaque<0>()); }
    void test1() { Opaque<1> _ = foo(Opaque<1>()); }
    void test2() { Opaque<0> _ = foo(Opaque<2>()); }
    void test3() { Opaque<1> _ = foo(Opaque<3>()); }
  };

  // using between decls
  struct Test2 : Base {
    Opaque<1> foo(Opaque<0>);
    using Base::foo;
    Opaque<1> foo(Opaque<2>);
    Opaque<1> foo(Opaque<3>);

    void test0() { Opaque<1> _ = foo(Opaque<0>()); }
    void test1() { Opaque<0> _ = foo(Opaque<1>()); }
    void test2() { Opaque<1> _ = foo(Opaque<2>()); }
    void test3() { Opaque<1> _ = foo(Opaque<3>()); }
  };
}

// Crazy dependent hiding.
namespace test2 {
  struct Base {
    void foo(int);
  };

  template <typename T> struct Derived1 : Base {
    using Base::foo;
    void foo(T);

    void testUnresolved(int i) { foo(i); }
  };

  void test0(int i) {
    Derived1<int> d1;
    d1.foo(i);
    d1.testUnresolved(i);
  }

  // Same thing, except with the order of members reversed.
  template <typename T> struct Derived2 : Base {
    void foo(T);
    using Base::foo;

    void testUnresolved(int i) { foo(i); }
  };

  void test1(int i) {
    Derived2<int> d2;
    d2.foo(i);
    d2.testUnresolved(i);
  }
}
