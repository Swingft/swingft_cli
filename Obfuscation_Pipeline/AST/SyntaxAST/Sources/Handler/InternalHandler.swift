//
//  InternalCode.swift
//  SyntaxAST
//
//  Created by 백승혜 on 8/4/25.
//

import Foundation

class InternalHandler {
    let sourceListPath: String
    let outputDir = "../output/source_json"
    let typealias_outputDir = "../output/typealias_json"
    
    init(sourceListPath: String) {
        self.sourceListPath = sourceListPath
    }

    func readAndProcess() throws {
        let fileList = try String(contentsOfFile: sourceListPath)
        let sourcePaths = fileList.split(separator: "\n").map { String($0) }
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
        var allImports = [Set<String>](repeating: [], count: sourcePaths.count)
        var allTypeResults = [[TypealiasInfo]](repeating: [], count: sourcePaths.count)
        
        DispatchQueue.concurrentPerform(iterations: sourcePaths.count) { index in let sourcePath = sourcePaths[index]
            do {
                let extractor = try Extractor(sourcePath: sourcePath)
                extractor.performExtraction()
                let (result, typealiasResult, importResult) = extractor.store.all()
                
                allTypeResults[index] = typealiasResult
                allImports[index] = importResult
                
                let jsonData = try encoder.encode(result)
                
                let sourceURL = URL(fileURLWithPath: sourcePath)
                let fileName = sourceURL.deletingPathExtension().lastPathComponent
                let fileNameWithCount = "\(index)_\(fileName)"
                
                var outputURL = URL(fileURLWithPath: outputDir)
                    .appendingPathComponent(fileNameWithCount)
                    .appendingPathExtension("json")
                
                try jsonData.write(to: outputURL)
            } catch {
                print("Error: \(error)")
            }
        }
        
        let importResult = allImports.flatMap { $0 }
        if !allImports.isEmpty {
            let importOutputFile = URL(fileURLWithPath: "../output/").appendingPathComponent("import_list.txt")
            let jsonData = try encoder.encode(importResult)
            try jsonData.write(to: importOutputFile)
        }
        
        let typeResult = allTypeResults.flatMap { $0 }
        if !typeResult.isEmpty {
            let fileName = "typealias"
            var outputURL = URL(fileURLWithPath: typealias_outputDir)
                .appendingPathComponent(fileName)
                .appendingPathExtension("json")
            let jsonData = try encoder.encode(typeResult)
            try jsonData.write(to: outputURL)
        }
    }
}


