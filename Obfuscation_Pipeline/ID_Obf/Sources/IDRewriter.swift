//
//  IDRewriter.swift
//  Parse
//
//  Created by 백승혜 on 9/29/25.
//

import SwiftSyntax

class IDRewriter: SyntaxRewriter {
    let mapping: [String: String]
    
    init(mapping: [String: String]) {
        self.mapping = mapping
        super.init()
    }
    
    override func visit(_ node: CodeBlockItemListSyntax) -> CodeBlockItemListSyntax{
        return super.visit(node)
    }
    override func visit(_ node: CodeBlockItemSyntax) -> CodeBlockItemSyntax{
        return super.visit(node)
    }
    
    override func visit(_ node: ProtocolDeclSyntax) -> DeclSyntax {
        let oldName = node.name
        if let repl = mapping[oldName.text] {
            let leadingTrivia = oldName.leadingTrivia
            let trailingTrivia = oldName.trailingTrivia
            let newName = TokenSyntax.identifier(repl)
                .with(\.leadingTrivia, leadingTrivia)
                .with(\.trailingTrivia, trailingTrivia)
            let newNode = node.with(\.name, newName)
            return super.visit(newNode)
        }
        return super.visit(node)
    }
    
    override func visit(_ node: ClassDeclSyntax) -> DeclSyntax {
        let oldName = node.name
        if let repl = mapping[oldName.text] {
            let leadingTrivia = oldName.leadingTrivia
            let trailingTrivia = oldName.trailingTrivia
            let newName = TokenSyntax.identifier(repl)
                .with(\.leadingTrivia, leadingTrivia)
                .with(\.trailingTrivia, trailingTrivia)
            let newNode = node.with(\.name, newName)
            return super.visit(newNode)
        }
        return super.visit(node)
    }
    
    override func visit(_ node: StructDeclSyntax) -> DeclSyntax {
        let oldName = node.name
        if let repl = mapping[oldName.text] {
            let leadingTrivia = oldName.leadingTrivia
            let trailingTrivia = oldName.trailingTrivia
            let newName = TokenSyntax.identifier(repl)
                .with(\.leadingTrivia, leadingTrivia)
                .with(\.trailingTrivia, trailingTrivia)
            let newNode = node.with(\.name, newName)
            return super.visit(newNode)
        }
        return super.visit(node)
    }
    
    override func visit(_ node: EnumDeclSyntax) -> DeclSyntax {
        let oldName = node.name
        if let repl = mapping[oldName.text] {
            let leadingTrivia = oldName.leadingTrivia
            let trailingTrivia = oldName.trailingTrivia
            let newName = TokenSyntax.identifier(repl)
                .with(\.leadingTrivia, leadingTrivia)
                .with(\.trailingTrivia, trailingTrivia)
            let newNode = node.with(\.name, newName)
            return super.visit(newNode)
        }
        return super.visit(node)
    }
    
    override func visit(_ node: ActorDeclSyntax) -> DeclSyntax {
        let oldName = node.name
        if let repl = mapping[oldName.text] {
            let leadingTrivia = oldName.leadingTrivia
            let trailingTrivia = oldName.trailingTrivia
            let newName = TokenSyntax.identifier(repl)
                .with(\.leadingTrivia, leadingTrivia)
                .with(\.trailingTrivia, trailingTrivia)
            let newNode = node.with(\.name, newName)
            return super.visit(newNode)
        }
        return super.visit(node)
    }
    
    override func visit(_ node: FunctionDeclSyntax) -> DeclSyntax {
        let oldName = node.name
        if let repl = mapping[oldName.text] {
            let leadingTrivia = oldName.leadingTrivia
            let trailingTrivia = oldName.trailingTrivia
            let newName = TokenSyntax.identifier(repl)
                .with(\.leadingTrivia, leadingTrivia)
                .with(\.trailingTrivia, trailingTrivia)
            let newNode = node.with(\.name, newName)
            return super.visit(newNode)
        }
        return super.visit(node)
    }
    
    // enum case
    override func visit(_ node: EnumCaseElementSyntax) -> EnumCaseElementSyntax {
        let oldName = node.name
        if let repl = mapping[oldName.text] {
            let leadingTrivia = oldName.leadingTrivia
            let trailingTrivia = oldName.trailingTrivia
            let newName = TokenSyntax.identifier(repl)
                .with(\.leadingTrivia, leadingTrivia)
                .with(\.trailingTrivia, trailingTrivia)
            let newNode = node.with(\.name, newName)
            return super.visit(newNode)
        }
        return super.visit(node)
    }
    override func visit(_ node: EnumCaseParameterClauseSyntax) -> EnumCaseParameterClauseSyntax {
        return super.visit(node)
    }
    override func visit(_ node: EnumCaseParameterListSyntax) -> EnumCaseParameterListSyntax {
        return super.visit(node)
    }
    override func visit(_ node: EnumCaseParameterSyntax) -> EnumCaseParameterSyntax {
        var newNode = node
        
        if let oldFirstNameToken = node.firstName,
           let repl = mapping[oldFirstNameToken.text] {
                
            let newFirstName = oldFirstNameToken.with(\.tokenKind, .identifier(repl))
            newNode = newNode.with(\.firstName, newFirstName)
        }

        if let oldSecondName = node.secondName,
           let repl = mapping[oldSecondName.text] {
            let newSecondName = TokenSyntax.identifier(repl)
                .with(\.leadingTrivia, oldSecondName.leadingTrivia)
                .with(\.trailingTrivia, oldSecondName.trailingTrivia)
            newNode = newNode.with(\.secondName, newSecondName)
        }
        
        return super.visit(newNode)
    }
    
    
    override func visit(_ node: ExtensionDeclSyntax) -> DeclSyntax {
        if let simpleType = node.extendedType.as(IdentifierTypeSyntax.self) {
            let oldName = simpleType.name
            
            if let repl = mapping[oldName.text] {
                let leadingTrivia = oldName.leadingTrivia
                var trailingTrivia = oldName.trailingTrivia
                
                let newName = TokenSyntax.identifier(repl)
                    .with(\.leadingTrivia, leadingTrivia)
                    .with(\.trailingTrivia, trailingTrivia)
                
                let newType = simpleType.with(\.name, newName)
                let newNode = node.with(\.extendedType, TypeSyntax(newType))
                
                return super.visit(newNode)
            }
            return super.visit(node)
        }
        return super.visit(node)
    }
    
    override func visit(_ node: AssociatedTypeDeclSyntax) -> DeclSyntax {
        var newNode = node
        let oldName = node.name
        if let repl = mapping[oldName.text] {
            let newName = TokenSyntax.identifier(repl)
                .with(\.leadingTrivia, oldName.leadingTrivia)
                .with(\.trailingTrivia, oldName.trailingTrivia)
            newNode = newNode.with(\.name, newName)
        }
        return super.visit(newNode)
    }
    
    override func visit(_ node: MemberTypeSyntax) -> TypeSyntax {
        var newNode = node
        
        let oldNameToken = node.name
        if let repl = mapping[oldNameToken.text] {
            let newNameToken = TokenSyntax.identifier(repl)
                .with(\.leadingTrivia, oldNameToken.leadingTrivia)
                .with(\.trailingTrivia, oldNameToken.trailingTrivia)
            
            newNode = newNode.with(\.name, newNameToken)
        }
        return super.visit(newNode)
    }
    
    // 변수, 타입
    override func visit(_ node: VariableDeclSyntax) -> DeclSyntax {
        let newBindings = PatternBindingListSyntax(
            node.bindings.map { binding -> PatternBindingSyntax in
                var newBinding = binding

                if let ident = binding.pattern.as(IdentifierPatternSyntax.self),
                    let repl = mapping[ident.identifier.text] {
                    let oldIdentifierToken = ident.identifier
                    
                    let newIdentifier = TokenSyntax.identifier(repl)
                        .with(\.leadingTrivia, oldIdentifierToken.leadingTrivia)
                        .with(\.trailingTrivia, oldIdentifierToken.trailingTrivia)
                    
                    let newPattern = ident.with(\.identifier, newIdentifier)
                    newBinding = newBinding.with(\.pattern, PatternSyntax(newPattern))
                }

                if let type = binding.typeAnnotation?.type.as(IdentifierTypeSyntax.self),
                    let replType = mapping[type.name.text] {
                    let oldTypeToken = type.name
                    
                    let newTypeIdentifier = TokenSyntax.identifier(replType)
                        .with(\.leadingTrivia, oldTypeToken.leadingTrivia)
                        .with(\.trailingTrivia, oldTypeToken.trailingTrivia)
                    
                    let newType = type.with(\.name, newTypeIdentifier)
                    let newTypeAnnotation = binding.typeAnnotation!.with(\.type, TypeSyntax(newType))
                    newBinding = newBinding.with(\.typeAnnotation, newTypeAnnotation)
                }
                return newBinding
            }
        )
        
        return super.visit(node.with(\.bindings, newBindings))
    }
    override func visit(_ node: AttributeListSyntax) -> AttributeListSyntax {
        return super.visit(node)
    }
    
    // 상수, 변수
    override func visit(_ node: IdentifierPatternSyntax) -> PatternSyntax {
        let oldName = node.identifier
        if let repl = mapping[oldName.text] {
            let leading = oldName.leadingTrivia
            let trailing = oldName.trailingTrivia
            let newName = TokenSyntax.identifier(repl)
                .with(\.leadingTrivia, leading)
                .with(\.trailingTrivia, trailing)
            let newNode = node.with(\.identifier, newName)
            return super.visit(newNode)
        }
        return super.visit(node)
    }
    
    override func visit(_ node: PatternBindingListSyntax) -> PatternBindingListSyntax {
        return super.visit(node)
    }
    override func visit(_ node: PatternBindingSyntax) -> PatternBindingSyntax {
        return super.visit(node)
    }
    override func visit(_ node: TypeAnnotationSyntax) -> TypeAnnotationSyntax {
        return super.visit(node)
    }
    
    override func visit(_ node: ArrayTypeSyntax) -> TypeSyntax {
        return super.visit(node)
    }
    
    override func visit(_ node: DeclModifierListSyntax) -> DeclModifierListSyntax {
        return super.visit(node)
    }
    
    // 참조
    override func visit(_ node: DeclReferenceExprSyntax) -> ExprSyntax {
        let oldName = node.baseName
        let oldName2 = oldName.text.hasPrefix("$") ? String(oldName.text.dropFirst()) : oldName.text
        
        if let repl = mapping[oldName2] {
            let leadingTrivia = oldName.leadingTrivia
            let trailingTrivia = oldName.trailingTrivia
            
            let finalName = oldName.text.hasPrefix("$") ? "$" + repl : repl
            
            let newName = TokenSyntax.identifier(finalName)
                .with(\.leadingTrivia, leadingTrivia)
                .with(\.trailingTrivia, trailingTrivia)
            
            let newNode = node.with(\.baseName, newName)
            return super.visit(newNode)
        }
        return super.visit(node)
    }
    override func visit(_ node: DeclNameArgumentsSyntax) -> DeclNameArgumentsSyntax {
        return super.visit(node)
    }
    override func visit(_ node: DeclNameArgumentListSyntax) -> DeclNameArgumentListSyntax {
        return super.visit(node)
    }
    override func visit(_ node: DeclNameArgumentSyntax) -> DeclNameArgumentSyntax {
        let oldName = node.name
        if let repl = mapping[oldName.text] {
            let leadingTrivia = oldName.leadingTrivia
            let trailingTrivia = oldName.trailingTrivia
            
            let newName = TokenSyntax.identifier(repl)
                        .with(\.leadingTrivia, leadingTrivia)
                        .with(\.trailingTrivia, trailingTrivia)
            
            let newNode = node.with(\.name, newName)
            
            return super.visit(newNode)
        }
        return super.visit(node)
    }
    
    override func visit(_ node: InitializerClauseSyntax) -> InitializerClauseSyntax {
        return super.visit(node)
    }
    
    // 멤버 접근
    override func visit(_ node: MemberBlockSyntax) -> MemberBlockSyntax {
        return super.visit(node)
    }
    override func visit(_ node: MemberBlockItemListSyntax) -> MemberBlockItemListSyntax {
        return super.visit(node)
    }
    override func visit(_ node: MemberBlockItemSyntax) -> MemberBlockItemSyntax {
        return super.visit(node)
    }
    
    override func visit(_ node: MemberAccessExprSyntax) -> ExprSyntax {
        let oldName = node.declName.baseName
        
        if let repl = mapping[oldName.text] {
            let leadingTrivia = oldName.leadingTrivia
            let trailingTrivia = oldName.trailingTrivia
            
            let newName = TokenSyntax.identifier(repl)
                        .with(\.leadingTrivia, leadingTrivia)
                        .with(\.trailingTrivia, trailingTrivia)
            
            let newNode = node.with(\.declName.baseName, newName)
            
            return super.visit(newNode)
        }
        return super.visit(node)
    }
    
    // 함수 파라미터
    override func visit(_ node: FunctionParameterSyntax) -> FunctionParameterSyntax {
        var newNode = node
        
        let oldFirstName = node.firstName
        if let repl = mapping[oldFirstName.text] {
            let newFirstName = TokenSyntax.identifier(repl)
                .with(\.leadingTrivia, oldFirstName.leadingTrivia)
                .with(\.trailingTrivia, oldFirstName.trailingTrivia)
            newNode = newNode.with(\.firstName, newFirstName)
        }

        if let oldSecondName = node.secondName,
           let repl = mapping[oldSecondName.text] {
            let newSecondName = TokenSyntax.identifier(repl)
                .with(\.leadingTrivia, oldSecondName.leadingTrivia)
                .with(\.trailingTrivia, oldSecondName.trailingTrivia)
            newNode = newNode.with(\.secondName, newSecondName)
        }
        
        return super.visit(newNode)
    }
    
    override func visit(_ node: FunctionParameterClauseSyntax) -> FunctionParameterClauseSyntax {
        return super.visit(node)
    }
    
    // 함수 라벨
    override func visit(_ node: LabeledExprSyntax) -> LabeledExprSyntax {
        guard let oldLabelToken = node.label else {
            return super.visit(node)
        }
        
        let oldLabelText = oldLabelToken.text
        
        if let repl = mapping[oldLabelText] {
            let leading = oldLabelToken.leadingTrivia
            let trailing = oldLabelToken.trailingTrivia
            let newLabelToken = TokenSyntax.identifier(repl)
                .with(\.leadingTrivia, leading)
                .with(\.trailingTrivia, trailing)
            let newNode = node.with(\.label, newLabelToken)
            return super.visit(newNode)
        }
        return super.visit(node)
    }
    
    override func visit(_ node: LabeledExprListSyntax) -> LabeledExprListSyntax {
        return super.visit(node)
    }
    
    override func visit(_ node: ArrayExprSyntax) -> ExprSyntax {
        return super.visit(node)
    }
    override func visit(_ node: ArrayElementListSyntax) -> ArrayElementListSyntax {
        return super.visit(node)
    }
    override func visit(_ node: ArrayElementSyntax) -> ArrayElementSyntax {
        return super.visit(node)
    }
    
    override func visit(_ node: FunctionCallExprSyntax) -> ExprSyntax {
        return super.visit(node)
    }
    
    // 타입 사용
    override func visit(_ node: IdentifierTypeSyntax) -> TypeSyntax {
        let oldName = node.name
        if let repl = mapping[oldName.text] {
            let leading = oldName.leadingTrivia
            let trailing = oldName.trailingTrivia
            let newName = TokenSyntax.identifier(repl)
                .with(\.leadingTrivia, leading)
                .with(\.trailingTrivia, trailing)
            let newNode = node.with(\.name, newName)
            return super.visit(newNode)
        }
        return super.visit(node)
    }
    
    // 제네릭 타입
    override func visit(_ node: GenericParameterSyntax) -> GenericParameterSyntax {
        let oldName = node.name
        if let repl = mapping[oldName.text] {
            let newName = TokenSyntax.identifier(repl)
                .with(\.leadingTrivia, oldName.leadingTrivia)
                .with(\.trailingTrivia, oldName.trailingTrivia)
            let newNode = node.with(\.name, newName)
            return super.visit(newNode)
        }
        return super.visit(node)
    }
    
    // 클로저 파라미터
    override func visit(_ node: ClosureParameterSyntax) -> ClosureParameterSyntax {
        var newNode = node
        
        let oldName = node.firstName
        if let repl = mapping[oldName.text] {
            let newName = TokenSyntax.identifier(repl)
                .with(\.leadingTrivia, oldName.leadingTrivia)
                .with(\.trailingTrivia, oldName.trailingTrivia)
            newNode = newNode.with(\.firstName, newName)
        }
        if let name = node.secondName, let repl = mapping[name.text] {
            let newName = TokenSyntax.identifier(repl)
                .with(\.leadingTrivia, name.leadingTrivia)
                .with(\.trailingTrivia, name.trailingTrivia)
            newNode = newNode.with(\.secondName, newName)
        }
        return super.visit(newNode)
    }
    override func visit(_ node: ClosureSignatureSyntax) -> ClosureSignatureSyntax {
        var newNode = node
        if let input = node.parameterClause?.as(IdentifierTypeSyntax.self) {
            let oldName = input.name
            if let repl = mapping[oldName.text] {
                let newName = TokenSyntax.identifier(repl)
                    .with(\.leadingTrivia, oldName.leadingTrivia)
                    .with(\.trailingTrivia, oldName.trailingTrivia)
                let newInput = input.with(\.name, newName)
                newNode = node.with(\.parameterClause, ClosureSignatureSyntax.ParameterClause(newInput))
            }
        }
        return super.visit(newNode)
    }
    override func visit(_ node: ClosureShorthandParameterSyntax) -> ClosureShorthandParameterSyntax {
        let oldName = node.name
        if let repl = mapping[oldName.text] {
            let newName = TokenSyntax.identifier(repl)
                .with(\.leadingTrivia, oldName.leadingTrivia)
                .with(\.trailingTrivia, oldName.trailingTrivia)
            let newNode = node.with(\.name, newName)
            return super.visit(newNode)
        }
        return super.visit(node)
    }
    override func visit(_ node: MultipleTrailingClosureElementSyntax) -> MultipleTrailingClosureElementSyntax {
        let oldName = node.label
        if let repl = mapping[oldName.text] {
            let newName = TokenSyntax.identifier(repl)
                .with(\.leadingTrivia, oldName.leadingTrivia)
                .with(\.trailingTrivia, oldName.trailingTrivia)
            let newNode = node.with(\.label, newName)
            return super.visit(newNode)
        }
        return super.visit(node)
    }
    override func visit(_ node: ClosureCaptureSyntax) -> ClosureCaptureSyntax {
        let oldName = node.name
        if let repl = mapping[oldName.text] {
            let newName = TokenSyntax.identifier(repl)
                .with(\.leadingTrivia, oldName.leadingTrivia)
                .with(\.trailingTrivia, oldName.trailingTrivia)
            let newNode = node.with(\.name, newName)
            return super.visit(newNode)
        }
        return super.visit(node)
    }
 
    override func visit(_ node: TupleTypeSyntax) -> TypeSyntax {
        return super.visit(node)
    }
    override func visit(_ node: TupleTypeElementListSyntax) -> TupleTypeElementListSyntax {
        return super.visit(node)
    }
    override func visit(_ node: TupleTypeElementSyntax) -> TupleTypeElementSyntax {
        var newNode = node
        
        if let oldFirstNameToken = node.firstName,
           let repl = mapping[oldFirstNameToken.text] {
                
            let newFirstName = oldFirstNameToken.with(\.tokenKind, .identifier(repl))
            newNode = newNode.with(\.firstName, newFirstName)
        }

        if let oldSecondName = node.secondName,
           let repl = mapping[oldSecondName.text] {
            let newSecondName = TokenSyntax.identifier(repl)
                .with(\.leadingTrivia, oldSecondName.leadingTrivia)
                .with(\.trailingTrivia, oldSecondName.trailingTrivia)
            newNode = newNode.with(\.secondName, newSecondName)
        }
        
        return super.visit(newNode)
    }
    
    // 매크로
    override func visit(_ node: MacroExpansionExprSyntax) -> ExprSyntax {
        return super.visit(node)
    }
    override func visit(_ node: ClosureExprSyntax) -> ExprSyntax {
        return super.visit(node)
    }
}
