//
//  ProcessResult.swift
//  SyntaxAST
//
//  Created by 백승혜 on 10/1/25.
//

import Foundation

struct ParseResult {
    let fileName: String
    let sourceJson: Data
    let typealiasResult: [TypealiasInfo]
}
