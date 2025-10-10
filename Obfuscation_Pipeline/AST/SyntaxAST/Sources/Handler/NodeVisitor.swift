//
//  Visitor.swift
//  SyntaxAST
//
//  Created by 백승혜 on 7/15/25.
//

//  AST 탐색

import SwiftSyntax

class Visitor: SyntaxVisitor {
    private let store: ResultStore
    private let location: LocationHandler
    
    init(store: ResultStore, location: LocationHandler) {
        self.store = store
        self.location = location
        super.init(viewMode: .sourceAccurate)
    }
    
    override func visit(_ node: ImportDeclSyntax) -> SyntaxVisitorContinueKind {
        if let path = node.path.first?.name.text {
            store.importAppend(path)
        }
        return .visitChildren
    }
    
    override func visit(_ node: TypeAliasDeclSyntax) -> SyntaxVisitorContinueKind {
        let aliasName = node.name.text
        var protocols: [String] = []
        
        let valueClause = node.initializer
        let type = valueClause.value
        if let composition = type.as(CompositionTypeSyntax.self) {
            let elements = composition.elements
            protocols = elements.map {
                $0.description.trimmingCharacters(in: .whitespacesAndNewlines)
            }
        }
        store.typealiasAppend(TypealiasInfo(aliasName: aliasName, protocols: protocols))
        return .visitChildren
    }
    
    override func visit(_ node: ProtocolDeclSyntax) -> SyntaxVisitorContinueKind {
        let info = ProtocolInfoExtractor.extract(from: node, locationHandler: location)
        store.nodeAppend(info)
        return .visitChildren
    }
    
    override func visit(_ node: ClassDeclSyntax) -> SyntaxVisitorContinueKind {
        let info = ClassInfoExtractor.extract(from: node, locationHandler: location)
        store.nodeAppend(info)
        return .visitChildren
    }
    
    override func visit(_ node: StructDeclSyntax) -> SyntaxVisitorContinueKind {
        let info = StructInfoExtractor.extract(from: node, locationHandler: location)
        store.nodeAppend(info)
        return .visitChildren
    }
    
    override func visit(_ node: ExtensionDeclSyntax) -> SyntaxVisitorContinueKind {
        let info = ExtensionInfoExtractor.extractor(from: node, locationHandler: location)
        store.nodeAppend(info)
        return .visitChildren
    }
    
    override func visit(_ node: FunctionDeclSyntax) -> SyntaxVisitorContinueKind {
        let info = FunctionInfoExtractor.extract(from: node, locationHandler: location)
        store.nodeAppend(info)
        return .visitChildren
    }
    
    override func visit(_ node: InitializerDeclSyntax) -> SyntaxVisitorContinueKind {
        let info = InitInfoExtractor.extract(from: node, locationHandler: location)
        store.nodeAppend(info)
        return .visitChildren
    }

    override func visit(_ node: VariableDeclSyntax) -> SyntaxVisitorContinueKind {
        let infos = VariableInfoExtractor.extract(from: node, locationHandler: location)
        
        for info in infos {
            store.nodeAppend(info)
        }
        
        return .visitChildren
    }
    
    override func visit(_ node: EnumDeclSyntax) -> SyntaxVisitorContinueKind {
        let info = EnumInfoExtractor.extract(from: node, locationHandler: location)
        store.nodeAppend(info)
        return .visitChildren
    }
    
    override func visit(_ node: ActorDeclSyntax) -> SyntaxVisitorContinueKind {
        let info = ActorInfoExtractor.extract(from: node, locationHandler: location)
        store.nodeAppend(info)
        return .visitChildren
    }
}
