// CFGWrappingUtils.swift
// 공통 CFG wrapping 유틸리티 함수들
import Foundation
public struct CFGWrappingUtils {
    public static func wrap0<R>(_ function: @escaping () -> R) -> ([Any]) throws -> Any {
        return { args in
            precondition(args.isEmpty)
            return function()
        }
    }

    public static func wrap1<A, R>(_ function: @escaping (A) -> R) -> ([Any]) throws -> Any {
        return { args in
            precondition(args.count == 1)
            guard let a0 = args[0] as? A else { preconditionFailure("[OBF] cast at 0") }
            return function(a0)
        }
    }

  public static func wrap2<A, B, R>(_ function: @escaping (A, B) -> R) -> ([Any]) throws -> Any {
    return { args in
      precondition(args.count == 2)
      guard let a0 = args[0] as? A else { preconditionFailure("[OBF] cast at 0") }
      guard let a1 = args[1] as? B else { preconditionFailure("[OBF] cast at 1") }
      return function(a0, a1)
    }
  }

  public static func wrap3<A, B, C, R>(_ function: @escaping (A, B, C) -> R) -> ([Any]) throws -> Any {
    return { args in
      precondition(args.count == 3)
      guard let a0 = args[0] as? A else { preconditionFailure("[OBF] cast at 0") }
      guard let a1 = args[1] as? B else { preconditionFailure("[OBF] cast at 1") }
      guard let a2 = args[2] as? C else { preconditionFailure("[OBF] cast at 2") }
      return function(a0, a1, a2)
    }
  }

  public static func wrap4<A, B, C, D, R>(_ function: @escaping (A, B, C, D) -> R) -> ([Any]) throws -> Any {
    return { args in
      precondition(args.count == 4)
      guard let a0 = args[0] as? A else { preconditionFailure("[OBF] cast at 0") }
      guard let a1 = args[1] as? B else { preconditionFailure("[OBF] cast at 1") }
      guard let a2 = args[2] as? C else { preconditionFailure("[OBF] cast at 2") }
      guard let a3 = args[3] as? D else { preconditionFailure("[OBF] cast at 3") }
      return function(a0, a1, a2, a3)
    }
  }

  public static func wrap5<A, B, C, D, E, R>(_ function: @escaping (A, B, C, D, E) -> R) -> ([Any]) throws -> Any {
    return { args in
      precondition(args.count == 5)
      guard let a0 = args[0] as? A else { preconditionFailure("[OBF] cast at 0") }
      guard let a1 = args[1] as? B else { preconditionFailure("[OBF] cast at 1") }
      guard let a2 = args[2] as? C else { preconditionFailure("[OBF] cast at 2") }
      guard let a3 = args[3] as? D else { preconditionFailure("[OBF] cast at 3") }
      guard let a4 = args[4] as? E else { preconditionFailure("[OBF] cast at 4") }
      return function(a0, a1, a2, a3, a4)
    }
  }

  public static func wrap6<A, B, C, D, E, F, R>(_ function: @escaping (A, B, C, D, E, F) -> R) -> ([Any]) throws -> Any {
    return { args in
      precondition(args.count == 6)
      guard let a0 = args[0] as? A else { preconditionFailure("[OBF] cast at 0") }
      guard let a1 = args[1] as? B else { preconditionFailure("[OBF] cast at 1") }
      guard let a2 = args[2] as? C else { preconditionFailure("[OBF] cast at 2") }
      guard let a3 = args[3] as? D else { preconditionFailure("[OBF] cast at 3") }
      guard let a4 = args[4] as? E else { preconditionFailure("[OBF] cast at 4") }
      guard let a5 = args[5] as? F else { preconditionFailure("[OBF] cast at 5") }
      return function(a0, a1, a2, a3, a4, a5)
    }
  }

  public static func wrap7<A, B, C, D, E, F, G, R>(_ function: @escaping (A, B, C, D, E, F, G) -> R) -> ([Any]) throws -> Any {
    return { args in
      precondition(args.count == 7)
      guard let a0 = args[0] as? A else { preconditionFailure("[OBF] cast at 0") }
      guard let a1 = args[1] as? B else { preconditionFailure("[OBF] cast at 1") }
      guard let a2 = args[2] as? C else { preconditionFailure("[OBF] cast at 2") }
      guard let a3 = args[3] as? D else { preconditionFailure("[OBF] cast at 3") }
      guard let a4 = args[4] as? E else { preconditionFailure("[OBF] cast at 4") }
      guard let a5 = args[5] as? F else { preconditionFailure("[OBF] cast at 5") }
      guard let a6 = args[6] as? G else { preconditionFailure("[OBF] cast at 6") }
      return function(a0, a1, a2, a3, a4, a5, a6)
    }
  }

  public static func wrap8<A, B, C, D, E, F, G, H, R>(_ function: @escaping (A, B, C, D, E, F, G, H) -> R) -> ([Any]) throws -> Any {
    return { args in
      precondition(args.count == 8)
      guard let a0 = args[0] as? A else { preconditionFailure("[OBF] cast at 0") }
      guard let a1 = args[1] as? B else { preconditionFailure("[OBF] cast at 1") }
      guard let a2 = args[2] as? C else { preconditionFailure("[OBF] cast at 2") }
      guard let a3 = args[3] as? D else { preconditionFailure("[OBF] cast at 3") }
      guard let a4 = args[4] as? E else { preconditionFailure("[OBF] cast at 4") }
      guard let a5 = args[5] as? F else { preconditionFailure("[OBF] cast at 5") }
      guard let a6 = args[6] as? G else { preconditionFailure("[OBF] cast at 6") }
      guard let a7 = args[7] as? H else { preconditionFailure("[OBF] cast at 7") }
      return function(a0, a1, a2, a3, a4, a5, a6, a7)
    }
  }

  public static func wrap9<A, B, C, D, E, F, G, H, I, R>(_ function: @escaping (A, B, C, D, E, F, G, H, I) -> R) -> ([Any]) throws -> Any {
    return { args in
      precondition(args.count == 9)
      guard let a0 = args[0] as? A else { preconditionFailure("[OBF] cast at 0") }
      guard let a1 = args[1] as? B else { preconditionFailure("[OBF] cast at 1") }
      guard let a2 = args[2] as? C else { preconditionFailure("[OBF] cast at 2") }
      guard let a3 = args[3] as? D else { preconditionFailure("[OBF] cast at 3") }
      guard let a4 = args[4] as? E else { preconditionFailure("[OBF] cast at 4") }
      guard let a5 = args[5] as? F else { preconditionFailure("[OBF] cast at 5") }
      guard let a6 = args[6] as? G else { preconditionFailure("[OBF] cast at 6") }
      guard let a7 = args[7] as? H else { preconditionFailure("[OBF] cast at 7") }
      guard let a8 = args[8] as? I else { preconditionFailure("[OBF] cast at 8") }
      return function(a0, a1, a2, a3, a4, a5, a6, a7, a8)
    }
  }

  public static func wrap10<A, B, C, D, E, F, G, H, I, J, R>(_ function: @escaping (A, B, C, D, E, F, G, H, I, J) -> R) -> ([Any]) throws -> Any {
    return { args in
      precondition(args.count == 10)
      guard let a0 = args[0] as? A else { preconditionFailure("[OBF] cast at 0") }
      guard let a1 = args[1] as? B else { preconditionFailure("[OBF] cast at 1") }
      guard let a2 = args[2] as? C else { preconditionFailure("[OBF] cast at 2") }
      guard let a3 = args[3] as? D else { preconditionFailure("[OBF] cast at 3") }
      guard let a4 = args[4] as? E else { preconditionFailure("[OBF] cast at 4") }
      guard let a5 = args[5] as? F else { preconditionFailure("[OBF] cast at 5") }
      guard let a6 = args[6] as? G else { preconditionFailure("[OBF] cast at 6") }
      guard let a7 = args[7] as? H else { preconditionFailure("[OBF] cast at 7") }
      guard let a8 = args[8] as? I else { preconditionFailure("[OBF] cast at 8") }
      guard let a9 = args[9] as? J else { preconditionFailure("[OBF] cast at 9") }
      return function(a0, a1, a2, a3, a4, a5, a6, a7, a8, a9)
    }
  }

  // Instance method wrappers
  public static func wrapM0<S, R>(_ function: @escaping (S) -> () -> R) -> ([Any]) throws -> Any {
    return { args in
      precondition(args.count == 1)
      guard let owner = args[0] as? S else { preconditionFailure("[OBF] cast self") }
      return function(owner)()
    }
  }

  public static func wrapM1<S, A, R>(_ function: @escaping (S) -> (A) -> R) -> ([Any]) throws -> Any {
    return { args in
      precondition(args.count == 2)
      guard let owner = args[0] as? S else { preconditionFailure("[OBF] cast self") }
      guard let a0 = args[1] as? A else { preconditionFailure("[OBF] cast at 0") }
      return function(owner)(a0)
    }
  }

  public static func wrapM2<S, A, B, R>(_ function: @escaping (S) -> (A, B) -> R) -> ([Any]) throws -> Any {
    return { args in
      precondition(args.count == 3)
      guard let owner = args[0] as? S else { preconditionFailure("[OBF] cast self") }
      guard let a0 = args[1] as? A else { preconditionFailure("[OBF] cast at 0") }
      guard let a1 = args[2] as? B else { preconditionFailure("[OBF] cast at 1") }
      return function(owner)(a0, a1)
    }
  }

  public static func wrapM3<S, A, B, C, R>(_ function: @escaping (S) -> (A, B, C) -> R) -> ([Any]) throws -> Any {
    return { args in
      precondition(args.count == 4)
      guard let owner = args[0] as? S else { preconditionFailure("[OBF] cast self") }
      guard let a0 = args[1] as? A else { preconditionFailure("[OBF] cast at 0") }
      guard let a1 = args[2] as? B else { preconditionFailure("[OBF] cast at 1") }
      guard let a2 = args[3] as? C else { preconditionFailure("[OBF] cast at 2") }
      return function(owner)(a0, a1, a2)
    }
  }

  public static func wrapM4<S, A, B, C, D, R>(_ function: @escaping (S) -> (A, B, C, D) -> R) -> ([Any]) throws -> Any {
    return { args in
      precondition(args.count == 5)
      guard let owner = args[0] as? S else { preconditionFailure("[OBF] cast self") }
      guard let a0 = args[1] as? A else { preconditionFailure("[OBF] cast at 0") }
      guard let a1 = args[2] as? B else { preconditionFailure("[OBF] cast at 1") }
      guard let a2 = args[3] as? C else { preconditionFailure("[OBF] cast at 2") }
      guard let a3 = args[4] as? D else { preconditionFailure("[OBF] cast at 3") }
      return function(owner)(a0, a1, a2, a3)
    }
  }

  public static func wrapM5<S, A, B, C, D, E, R>(_ function: @escaping (S) -> (A, B, C, D, E) -> R) -> ([Any]) throws -> Any {
    return { args in
      precondition(args.count == 6)
      guard let owner = args[0] as? S else { preconditionFailure("[OBF] cast self") }
      guard let a0 = args[1] as? A else { preconditionFailure("[OBF] cast at 0") }
      guard let a1 = args[2] as? B else { preconditionFailure("[OBF] cast at 1") }
      guard let a2 = args[3] as? C else { preconditionFailure("[OBF] cast at 2") }
      guard let a3 = args[4] as? D else { preconditionFailure("[OBF] cast at 3") }
      guard let a4 = args[5] as? E else { preconditionFailure("[OBF] cast at 4") }
      return function(owner)(a0, a1, a2, a3, a4)
    }
  }

  public static func wrapM6<S, A, B, C, D, E, F, R>(_ function: @escaping (S) -> (A, B, C, D, E, F) -> R) -> ([Any]) throws -> Any {
    return { args in
      precondition(args.count == 7)
      guard let owner = args[0] as? S else { preconditionFailure("[OBF] cast self") }
      guard let a0 = args[1] as? A else { preconditionFailure("[OBF] cast at 0") }
      guard let a1 = args[2] as? B else { preconditionFailure("[OBF] cast at 1") }
      guard let a2 = args[3] as? C else { preconditionFailure("[OBF] cast at 2") }
      guard let a3 = args[4] as? D else { preconditionFailure("[OBF] cast at 3") }
      guard let a4 = args[5] as? E else { preconditionFailure("[OBF] cast at 4") }
      guard let a5 = args[6] as? F else { preconditionFailure("[OBF] cast at 5") }
      return function(owner)(a0, a1, a2, a3, a4, a5)
    }
  }

  public static func wrapM7<S, A, B, C, D, E, F, G, R>(_ function: @escaping (S) -> (A, B, C, D, E, F, G) -> R) -> ([Any]) throws -> Any {
    return { args in
      precondition(args.count == 8)
      guard let owner = args[0] as? S else { preconditionFailure("[OBF] cast self") }
      guard let a0 = args[1] as? A else { preconditionFailure("[OBF] cast at 0") }
      guard let a1 = args[2] as? B else { preconditionFailure("[OBF] cast at 1") }
      guard let a2 = args[3] as? C else { preconditionFailure("[OBF] cast at 2") }
      guard let a3 = args[4] as? D else { preconditionFailure("[OBF] cast at 3") }
      guard let a4 = args[5] as? E else { preconditionFailure("[OBF] cast at 4") }
      guard let a5 = args[6] as? F else { preconditionFailure("[OBF] cast at 5") }
      guard let a6 = args[7] as? G else { preconditionFailure("[OBF] cast at 6") }
      return function(owner)(a0, a1, a2, a3, a4, a5, a6)
    }
  }

  public static func wrapM8<S, A, B, C, D, E, F, G, H, R>(_ function: @escaping (S) -> (A, B, C, D, E, F, G, H) -> R) -> ([Any]) throws -> Any {
    return { args in
      precondition(args.count == 9)
      guard let owner = args[0] as? S else { preconditionFailure("[OBF] cast self") }
      guard let a0 = args[1] as? A else { preconditionFailure("[OBF] cast at 0") }
      guard let a1 = args[2] as? B else { preconditionFailure("[OBF] cast at 1") }
      guard let a2 = args[3] as? C else { preconditionFailure("[OBF] cast at 2") }
      guard let a3 = args[4] as? D else { preconditionFailure("[OBF] cast at 3") }
      guard let a4 = args[5] as? E else { preconditionFailure("[OBF] cast at 4") }
      guard let a5 = args[6] as? F else { preconditionFailure("[OBF] cast at 5") }
      guard let a6 = args[7] as? G else { preconditionFailure("[OBF] cast at 6") }
      guard let a7 = args[8] as? H else { preconditionFailure("[OBF] cast at 7") }
      return function(owner)(a0, a1, a2, a3, a4, a5, a6, a7)
    }
  }

  public static func wrapM9<S, A, B, C, D, E, F, G, H, I, R>(_ function: @escaping (S) -> (A, B, C, D, E, F, G, H, I) -> R) -> ([Any]) throws -> Any {
    return { args in
      precondition(args.count == 10)
      guard let owner = args[0] as? S else { preconditionFailure("[OBF] cast self") }
      guard let a0 = args[1] as? A else { preconditionFailure("[OBF] cast at 0") }
      guard let a1 = args[2] as? B else { preconditionFailure("[OBF] cast at 1") }
      guard let a2 = args[3] as? C else { preconditionFailure("[OBF] cast at 2") }
      guard let a3 = args[4] as? D else { preconditionFailure("[OBF] cast at 3") }
      guard let a4 = args[5] as? E else { preconditionFailure("[OBF] cast at 4") }
      guard let a5 = args[6] as? F else { preconditionFailure("[OBF] cast at 5") }
      guard let a6 = args[7] as? G else { preconditionFailure("[OBF] cast at 6") }
      guard let a7 = args[8] as? H else { preconditionFailure("[OBF] cast at 7") }
      guard let a8 = args[9] as? I else { preconditionFailure("[OBF] cast at 8") }
      return function(owner)(a0, a1, a2, a3, a4, a5, a6, a7, a8)
    }
  }

  public static func wrapM10<S, A, B, C, D, E, F, G, H, I, J, R>(_ function: @escaping (S) -> (A, B, C, D, E, F, G, H, I, J) -> R) -> ([Any]) throws -> Any {
    return { args in
      precondition(args.count == 11)
      guard let owner = args[0] as? S else { preconditionFailure("[OBF] cast self") }
      guard let a0 = args[1] as? A else { preconditionFailure("[OBF] cast at 0") }
      guard let a1 = args[2] as? B else { preconditionFailure("[OBF] cast at 1") }
      guard let a2 = args[3] as? C else { preconditionFailure("[OBF] cast at 2") }
      guard let a3 = args[4] as? D else { preconditionFailure("[OBF] cast at 3") }
      guard let a4 = args[5] as? E else { preconditionFailure("[OBF] cast at 4") }
      guard let a5 = args[6] as? F else { preconditionFailure("[OBF] cast at 5") }
      guard let a6 = args[7] as? G else { preconditionFailure("[OBF] cast at 6") }
      guard let a7 = args[8] as? H else { preconditionFailure("[OBF] cast at 7") }
      guard let a8 = args[9] as? I else { preconditionFailure("[OBF] cast at 8") }
      guard let a9 = args[10] as? J else { preconditionFailure("[OBF] cast at 9") }
      return function(owner)(a0, a1, a2, a3, a4, a5, a6, a7, a8, a9)
    }
  }
}
