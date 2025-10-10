import Foundation
import SwiftSyntax

enum SourceLoc {
    static func line(of node: some SyntaxProtocol, filePath: String) -> Int {
        let converter = SourceLocationConverter(fileName: filePath, tree: node.root)
        #if swift(<5.10)
        return node.startLocation(converter: converter).line ?? 0
        #else
        return node.startLocation(converter: converter).line
        #endif
    }
}
