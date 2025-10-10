//
//  InitInfoExtractor.swift
//  SyntaxAST
//
//  Created by 백승혜 on 9/19/25.
//

import SwiftSyntax

struct InitInfoExtractor {
    static func extract(from node: InitializerDeclSyntax, locationHandler locationHandler: LocationHandler) -> IdentifierInfo {
        let name = "init"
        let kind = "function"
        
        let accessLevels = ["private", "fileprivate", "internal", "public", "open"]
        let accessLevel = node.modifiers.compactMap { modifier -> String? in
            let name = modifier.name.text
            return name
        }.first ?? "internal"
        
        let modifiers = node.modifiers ?? []
        let otherMods = modifiers.compactMap { modifier -> String? in
            let name = modifier.name.text
            return accessLevels.contains(name) ? nil : name
        }
        var attributes = (node.attributes ?? []).compactMap {
            $0.as(AttributeSyntax.self)?.attributeName.description.trimmingCharacters(in: .whitespacesAndNewlines)
        }
        attributes.append(contentsOf: otherMods)
 
        let location = locationHandler.findLocation(of: node)
        
        var memberList: [IdentifierInfo] = []
        if let body = node.body {
            for stmt in body.statements {
                if let varDecl = stmt.item.as(VariableDeclSyntax.self) {
                    memberList.append(contentsOf: VariableInfoExtractor.extract(from: varDecl, locationHandler: locationHandler))
                }
            }
        }
        
        var parameters: [String] = []
        var parameterType: [String] = []
        if let parameterClause = node.signature.input as? ParameterClauseSyntax {
            for param in parameterClause.parameters {
                let internalName = param.firstName.text ?? ""
                let typeText = param.type.description.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
                parameters.append(internalName)
                parameterType.append(typeText)
            }
        }
        
        var returnType: String?
        if let returnClause = node.signature.output {
            returnType = returnClause.description.trimmingCharacters(in: .whitespacesAndNewlines)
        }
        
        return IdentifierInfo(
            A_name: name,
            B_kind: kind,
            C_accessLevel: accessLevel,
            D_attributes: attributes,
            F_location: location,
            G_members: memberList,
            I_parameters: parameters,
            I_parameterType: parameterType
        )
    }
}
