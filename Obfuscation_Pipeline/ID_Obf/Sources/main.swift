// The Swift Programming Language
// https://docs.swift.org/swift-book

import Foundation
import SwiftParser

let mappingResultPath = CommandLine.arguments[1]
let sourceListPath = CommandLine.arguments[2]

let result = try readMappingResult(from: URL(filePath: mappingResultPath))
let mappingDict = result.reduce(into: [String: String]()) { dict, item in
    dict[item.target] = item.replacement
}

print(mappingDict)

let fileList = try String(contentsOfFile: sourceListPath)
let sourcePaths = fileList.split(separator: "\n").map { String($0) }

for path in sourcePaths {
    let url = URL(fileURLWithPath: path)
    let sourceText = try String(contentsOf: url)
    let syntaxTree = try Parser.parse(source: sourceText)
    
    let rewriter = IDRewriter(mapping: mappingDict)
    let newSyntaxTree = rewriter.visit(syntaxTree)
    
    try newSyntaxTree.description.write(to: URL(fileURLWithPath: path), atomically: true, encoding: .utf8)
    print("Processed:", path)
    print(newSyntaxTree.description)
}

//let tree = try Parser.parse(source: """
//            SQLiteDictionaryBoolValuePublisher.show(vc: self){
//                try await SkipCountSink.shared.updateActionButton(vcPlanId: self.autocompleteAddCustomUrl!.vcPlanId,
//                                                            issuer: self.autocompleteAddCustomUrl!.issuer,
//                                                            offerId: self.autocompleteAddCustomUrl!.offerId)
//            } completeClosure: {
//                let profile = SkipCountSink.shared.removeAccessories()!.profile
//                
//                DispatchQueue.main.async
//                {
//                    self.vcNmLbl.text = profile.title
//                    
//                    self.issuerInfoLbl.text = "The certificate will be issued by "+(profile.profile.issuer.name)
//                    self.issuanceDateLbl.text = "Issuance Application Date:\n "+OCKChecklistTaskViewController.recordAction(dateString: (profile.proof?.created)!)!
//                    self.IssueInfoDescLbl.text = "The identity certificate issued by "+(profile.profile.issuer.name) + " is stored in this certificate."
//                }
//                
//            } failureCloseClosure: { title, message in
//                GifConvertListView.launchAndWait(title: title,
//                                          content: message,
//                                          VC: self)
//            }
//""")
//print(tree.debugDescription)
