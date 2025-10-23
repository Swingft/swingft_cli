import Foundation

struct SymbolGraph: Codable {
    var metadata: Metadata
    var symbols: [SymbolNode]
    var edges: [SymbolEdge]
}

struct Metadata: Codable {
    let projectPath: String
    let analyzedAt: String
}

struct SymbolNode: Codable, Hashable, Identifiable {
    let id: String
    var name: String
    var kind: SymbolKind
    var location: SourceLocation?
    var attributes: [String]
    var modifiers: [String]
    var typeName: String?

    // ✅ 추가: 부모 정보
    var parentId: String?
    var parentName: String?

    // 상속 체인
    var typeInheritanceChain: [String]?

    var isSystemSymbol: Bool = false
    var isReferencedByExternalFile: Bool = false
}

struct SymbolEdge: Codable, Hashable {
    let from: String
    let to: String
    let type: EdgeType
}

struct SourceLocation: Codable, Hashable {
    let file: String
    let line: Int
    let column: Int
}

enum SymbolKind: String, Codable, Hashable {
    case `class`, `struct`, `enum`, `protocol`, method, property, function, unknown, initializer, `subscript`, `operator`, enumCase
}

enum EdgeType: String, Codable, Hashable {
    case inheritsFrom = "INHERITS_FROM"
    case conformsTo = "CONFORMS_TO"
    case overrides = "OVERRIDES"
    case contains = "CONTAINS"
    case isOfType = "IS_OF_TYPE"
}