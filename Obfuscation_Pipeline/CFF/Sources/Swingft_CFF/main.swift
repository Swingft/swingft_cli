import Foundation
import SwiftSyntax
import SwiftParser

struct Clause: Codable {
    let role: String
    let condition: String?
    let statements: [String]
    let children: [IfChain]
}

struct IfChain: Codable {
    let path: String
    let parentFunc: String?
    let clauses: [Clause]
    let text: String
}

enum LoopKind: String, Codable { case whileLoop, forIn, repeatWhile }

struct LoopNode: Codable {
    let kind: LoopKind
    let path: String
    let parentFunc: String?
    let header: String
    let bodyStatements: [String]
    let text: String
    let nestedIfs: [IfChain]
    let nestedLoops: [LoopNode]
}

struct ASTBundle: Codable {
    let ifChains: [IfChain]
    let loops: [LoopNode]
}


private extension CodeBlockSyntax {
    func extractStatements() -> [String] {
        self.statements.map { $0.item.trimmedDescription }
    }
}



private struct IfNode {
    let conditions: String
    let body: CodeBlockSyntax
    let elseBodySyntax: Syntax?
    let original: Syntax
}
private func adaptIfNode(_ syn: Syntax) -> IfNode? {
    guard let e = syn.as(IfExprSyntax.self) else { return nil }
    return IfNode(
        conditions: e.conditions.trimmedDescription,
        body: e.body,
        elseBodySyntax: e.elseBody.map { Syntax($0) },
        original: Syntax(e)
    )
}



private struct WhileAdapted {
    let condition: String
    let body: CodeBlockSyntax
    let original: Syntax
}
private func adaptWhile(_ syn: Syntax) -> WhileAdapted? {
    guard let s = syn.as(WhileStmtSyntax.self) else { return nil }
    return WhileAdapted(condition: s.conditions.trimmedDescription,
                        body: s.body,
                        original: Syntax(s))
}

private struct ForInAdapted {
    let pattern: String
    let sequence: String
    let whereClause: String?
    let body: CodeBlockSyntax
    let original: Syntax
}
private func adaptForIn(_ syn: Syntax) -> ForInAdapted? {

    guard let s = syn.as(ForStmtSyntax.self) else { return nil }
    return ForInAdapted(
        pattern: s.pattern.trimmedDescription,
        sequence: s.sequence.trimmedDescription,
        whereClause: s.whereClause.map { $0.condition.trimmedDescription },
        body: s.body,
        original: Syntax(s)
    )
}

private struct RepeatWhileAdapted {
    let condition: String
    let body: CodeBlockSyntax
    let original: Syntax
}
private func adaptRepeatWhile(_ syn: Syntax) -> RepeatWhileAdapted? {

    guard let s = syn.as(RepeatStmtSyntax.self) else { return nil }
    return RepeatWhileAdapted(
        condition: s.condition.trimmedDescription,
        body: s.body,
        original: Syntax(s)
    )
}


final class IfCollector: SyntaxVisitor {
    private let filePath: String
    private(set) var chains: [IfChain] = []

    private struct FuncCtx { let name: String; let isUIBuilder: Bool }
    private var funcStack: [FuncCtx] = []

   
    private var inSwitch: Int = 0

    init(filePath: String) {
        self.filePath = filePath
        super.init(viewMode: .sourceAccurate)
    }


    private func isPureBooleanCondition(_ cond: String) -> Bool {
        let s = cond.replacingOccurrences(of: " ", with: "")
        let redFlags = ["iflet", "ifvar", "let", "var", "case", "#available"]
        if redFlags.contains(where: { s.lowercased().contains($0) }) { return false }
        if s.contains("=") && !s.contains("==") && !s.contains("!=") { return false }
        return true
    }

    private var inUIBuilderContext: Bool { funcStack.last?.isUIBuilder ?? false }


    private func isInsideUIBuilderContainers(_ node: Syntax) -> Bool {

        let uiContainers: Set<String> = [
            "HStack","VStack","ZStack","List","ForEach","Group","Section",
            "NavigationStack","NavigationView","Form","ScrollView","LazyVStack","LazyHStack",
            "LazyVGrid","LazyHGrid","TabView","Grid","GridRow"
        ]
        var parent = node.parent
        while let p = parent {
            if let call = p.as(FunctionCallExprSyntax.self) {
                let name = call.calledExpression.trimmedDescription
                if uiContainers.contains(name) { return true }
            }
            parent = p.parent
        }
        return false
    }


    private func isInsideViewProperty(_ node: Syntax) -> Bool {
        var p: Syntax? = node.parent
        while let cur = p {
            if let v = cur.as(VariableDeclSyntax.self) {

                let attrText = v.attributes.trimmedDescription.lowercased()
                if attrText.contains("viewbuilder") || attrText.contains("resultbuilder") {
                    return true
                }
                for b in v.bindings {
                    if let ty = b.typeAnnotation?.type.trimmedDescription {
                        if ty.contains("some View") || ty.contains("View") { return true }
                    }
                }
            }
            p = cur.parent
        }
        return false
    }

    private func shouldStore(_ ifNode: IfNode, node: Syntax) -> Bool {
       
        if inSwitch > 0 { return false }
        if !isPureBooleanCondition(ifNode.conditions) { return false }
        if inUIBuilderContext { return false }
        if isInsideUIBuilderContainers(node) { return false }
        if isInsideViewProperty(node) { return false }
        return true
    }

    private func nestedIfs(in block: CodeBlockSyntax?) -> [IfChain] {
        guard let stmts = block?.statements else { return [] }
        var result: [IfChain] = []
        for item in stmts {
            let syn = Syntax(item.item)

         
            if syn.is(SwitchExprSyntax.self) { continue }

            if let adapted = adaptIfNode(syn), shouldStore(adapted, node: syn) {
                result.append(buildChain(from: adapted))
                continue
            }
            for child in syn.children(viewMode: .sourceAccurate) {
            
                if child.is(SwitchExprSyntax.self) { continue }
                if let adapted = adaptIfNode(child), shouldStore(adapted, node: child) {
                    result.append(buildChain(from: adapted))
                    break
                }
            }
        }
        return result
    }

    private func buildChain(from ifNode: IfNode) -> IfChain {
        var clauses: [Clause] = []
        clauses.append(Clause(
            role: "if",
            condition: ifNode.conditions,
            statements: ifNode.body.extractStatements(),
            children: nestedIfs(in: ifNode.body)
        ))
        var cursor: Syntax? = ifNode.elseBodySyntax
        while let e = cursor {
            if let adapted = adaptIfNode(e) {

                clauses.append(Clause(
                    role: "elseif",
                    condition: adapted.conditions,
                    statements: adapted.body.extractStatements(),
                    children: nestedIfs(in: adapted.body)
                ))
                cursor = adapted.elseBodySyntax
            } else if let els = e.as(CodeBlockSyntax.self) {
                clauses.append(Clause(
                    role: "else",
                    condition: nil,
                    statements: els.extractStatements(),
                    children: nestedIfs(in: els)
                ))
                break
            } else {
                break
            }
        }

        return IfChain(path: filePath,
                       parentFunc: funcStack.last?.name,
                       clauses: clauses,
                       text: ifNode.original.trimmedDescription)
    }

    override func visit(_ node: FunctionDeclSyntax) -> SyntaxVisitorContinueKind {

        let attrs = node.attributes.trimmedDescription
        let retTy = node.signature.returnClause?.type.trimmedDescription ?? ""
        let isUIB = attrs.localizedCaseInsensitiveContains("viewbuilder")
                  || attrs.localizedCaseInsensitiveContains("resultbuilder")
                  || retTy.contains("some View")
                  || retTy.contains("View")
        funcStack.append(FuncCtx(name: node.name.trimmedDescription, isUIBuilder: isUIB))
        return .visitChildren
    }
    override func visitPost(_ node: FunctionDeclSyntax) { _ = funcStack.popLast() }

    
    override func visit(_ node: SwitchExprSyntax) -> SyntaxVisitorContinueKind {
        inSwitch += 1
        return .visitChildren
    }
    override func visitPost(_ node: SwitchExprSyntax) {
        inSwitch -= 1
    }

    override func visit(_ node: IfExprSyntax) -> SyntaxVisitorContinueKind {
        if let adapted = adaptIfNode(Syntax(node)), shouldStore(adapted, node: Syntax(node)) {
            chains.append(buildChain(from: adapted))
        }
        return .skipChildren
    }
}


final class LoopCollector: SyntaxVisitor {
    private let filePath: String
    private(set) var loops: [LoopNode] = []

    private struct FuncCtx { let name: String; let isUIBuilder: Bool }
    private var funcStack: [FuncCtx] = []

  
    private var inSwitch: Int = 0

    init(filePath: String) {
        self.filePath = filePath
        super.init(viewMode: .sourceAccurate)
    }

    private func nestedIfs(in block: CodeBlockSyntax?) -> [IfChain] {
        let ifc = IfCollector(filePath: filePath)
        if let blk = block { ifc.walk(blk) }
        return ifc.chains
    }
    private func nestedLoops(in block: CodeBlockSyntax?) -> [LoopNode] {
        let lc = LoopCollector(filePath: filePath)
        if let blk = block { lc.walk(blk) }
        return lc.loops
    }
    private func containsVarDecl(_ node: Syntax) -> Bool {
        if node.is(VariableDeclSyntax.self) { return true }
        for ch in node.children(viewMode: .sourceAccurate) {
            if containsVarDecl(ch) { return true }
        }
        return false
    }

    private func hasLetOrVarDecl(in block: CodeBlockSyntax) -> Bool {
        return containsVarDecl(Syntax(block))
    }

    private func patternHasLetOrVar(_ patternText: String) -> Bool {
        let p = patternText.trimmingCharacters(in: .whitespacesAndNewlines)
        return p.contains("var ") || p.contains("let ")
    }

    private func buildWhile(_ w: WhileAdapted) -> LoopNode {
        LoopNode(kind: .whileLoop,
                 path: filePath,
                 parentFunc: funcStack.last?.name,
                 header: w.condition,
                 bodyStatements: w.body.extractStatements(),
                 text: w.original.trimmedDescription,
                 nestedIfs: nestedIfs(in: w.body),
                 nestedLoops: nestedLoops(in: w.body))
    }
    private func buildForIn(_ f: ForInAdapted) -> LoopNode {
        let hdr = f.whereClause != nil
            ? "\(f.pattern) in \(f.sequence) where \(f.whereClause!)"
            : "\(f.pattern) in \(f.sequence)"
        return LoopNode(kind: .forIn,
                        path: filePath,
                        parentFunc: funcStack.last?.name,
                        header: hdr,
                        bodyStatements: f.body.extractStatements(),
                        text: f.original.trimmedDescription,
                        nestedIfs: nestedIfs(in: f.body),
                        nestedLoops: nestedLoops(in: f.body))
    }
    private func buildRepeatWhile(_ r: RepeatWhileAdapted) -> LoopNode {
        LoopNode(kind: .repeatWhile,
                 path: filePath,
                 parentFunc: funcStack.last?.name,
                 header: r.condition,
                 bodyStatements: r.body.extractStatements(),
                 text: r.original.trimmedDescription,
                 nestedIfs: nestedIfs(in: r.body),
                 nestedLoops: nestedLoops(in: r.body))
    }

    override func visit(_ node: FunctionDeclSyntax) -> SyntaxVisitorContinueKind {
        let attrs = node.attributes.trimmedDescription
        let retTy = node.signature.returnClause?.type.trimmedDescription ?? ""
        let isUIB = attrs.localizedCaseInsensitiveContains("viewbuilder")
                  || attrs.localizedCaseInsensitiveContains("resultbuilder")
                  || retTy.contains("some View")
                  || retTy.contains("View")
        funcStack.append(FuncCtx(name: node.name.trimmedDescription, isUIBuilder: isUIB))
        return .visitChildren
    }
    override func visitPost(_ node: FunctionDeclSyntax) { _ = funcStack.popLast() }

   
    override func visit(_ node: SwitchExprSyntax) -> SyntaxVisitorContinueKind {
        inSwitch += 1
        return .visitChildren
    }
    override func visitPost(_ node: SwitchExprSyntax) {
        inSwitch -= 1
    }

    override func visit(_ node: WhileStmtSyntax) -> SyntaxVisitorContinueKind {
        if inSwitch > 0 { return .skipChildren }
        if let w = adaptWhile(Syntax(node)) { loops.append(buildWhile(w)) }
        return .skipChildren
    }
    override func visit(_ node: ForStmtSyntax) -> SyntaxVisitorContinueKind {
        if inSwitch > 0 { return .skipChildren }
        if let f = adaptForIn(Syntax(node)) {
            if patternHasLetOrVar(f.pattern) || hasLetOrVarDecl(in: f.body) {
                return .skipChildren
            }
            loops.append(buildForIn(f))
        }
        return .skipChildren
    }

    override func visit(_ node: RepeatStmtSyntax) -> SyntaxVisitorContinueKind {
        if inSwitch > 0 { return .skipChildren }
        if let r = adaptRepeatWhile(Syntax(node)) { loops.append(buildRepeatWhile(r)) }
        return .skipChildren
    }
}



private func shouldSkipDirectory(_ url: URL) -> Bool {
    let name = url.lastPathComponent
        if name.hasPrefix(".") { return true }   
        if name == "Pods" { return true }
        return false
}
private func findSwiftFiles(at root: URL) -> [URL] {
    var files: [URL] = []
    let fm = FileManager.default
    guard let en = fm.enumerator(at: root,
                                 includingPropertiesForKeys: [.isDirectoryKey],
                                 options: [.skipsHiddenFiles])
    else { return [] }
    for case let url as URL in en {
        if (try? url.resourceValues(forKeys: [.isDirectoryKey]).isDirectory) == true {
            if shouldSkipDirectory(url) {
                en.skipDescendants()
                continue
            }
        }
        if url.pathExtension == "swift", !url.lastPathComponent.hasPrefix(".") {
            files.append(url)
        }
    }
    return files
}
private func runAndCapture(_ exe: String, _ args: [String]) -> (Int32, String) {
    let p = Process()
    p.executableURL = URL(fileURLWithPath: exe)
    p.arguments = args
    let pipe = Pipe()
    p.standardOutput = pipe
    p.standardError = pipe
    do { try p.run() } catch { return (126, "LAUNCH ERROR: \(error)") }
    p.waitUntilExit()
    let out = String(data: pipe.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8) ?? ""
    return (p.terminationStatus, out)
}

private func resolvePython3Command() -> [String]? {

    let candidates: [[String]] = [
        ["python3"], ["py","-3"]
    ]
    for cmd in candidates {
        let (st, out) = runAndCapture("/usr/bin/env", cmd + ["-c", "import sys; print(sys.version_info[0])"])
        if st == 0, out.trimmingCharacters(in: .whitespacesAndNewlines) == "3" { return cmd }
    }
    return nil
}

func runSwiftCFF(pyEnvAST: String, diffOutDir: String?) -> Int32 {

    let cwd = URL(fileURLWithPath: FileManager.default.currentDirectoryPath, isDirectory: true)
    let script = cwd.appendingPathComponent("run_swiftCFF.py")
    guard FileManager.default.fileExists(atPath: script.path) else {
        fputs("ERROR: run_swiftCFF.py Not found in the current folder.\n", stderr)
        return 127
    }
    guard let py = resolvePython3Command() else {
        fputs("ERROR: Python 3 Interpreter not found. Add python3 or python (3.x) to PATH.\n", stderr)
        return 127
    }

    let proc = Process()
    proc.executableURL = URL(fileURLWithPath: "/usr/bin/env")
    proc.arguments = py + [script.path]


    var env = ProcessInfo.processInfo.environment
    env["CFF_AST"] = pyEnvAST
    if let d = diffOutDir {
        env["CFF_DIFF_DIR"] = d
        env["CFF_USE_TIMESTAMP"] = "0"
    }
    proc.environment = env


    let pipe = Pipe()
    proc.standardOutput = pipe
    proc.standardError  = pipe
    do { try proc.run() } catch {
        fputs("ERROR: python 실행 실패: \(error)\n", stderr)
        return 126
    }
    let fh = pipe.fileHandleForReading
    fh.readabilityHandler = { h in
        if let s = String(data: h.availableData, encoding: .utf8), !s.isEmpty {
            fputs(s, stdout)
        }
    }
    proc.waitUntilExit()
    fh.readabilityHandler = nil
    return proc.terminationStatus
}


let inputPath = CommandLine.arguments.dropFirst().first ?? FileManager.default.currentDirectoryPath
let rootURL = URL(fileURLWithPath: inputPath, isDirectory: true)

var allIfs: [IfChain] = []
var allLoops: [LoopNode] = []

let swiftFiles = findSwiftFiles(at: rootURL)
for fileURL in swiftFiles {
    do {
        let src = try String(contentsOf: fileURL, encoding: .utf8)
        let tree = Parser.parse(source: src)

        let ic = IfCollector(filePath: fileURL.path)
        ic.walk(tree)
        allIfs.append(contentsOf: ic.chains)

        let lc = LoopCollector(filePath: fileURL.path)
        lc.walk(tree)
        allLoops.append(contentsOf: lc.loops)

    } catch {
        fputs("Parse error in \(fileURL.path): \(error)\n", stderr)
    }
}

let bundle = ASTBundle(ifChains: allIfs, loops: allLoops)
let outURL = URL(fileURLWithPath: FileManager.default.currentDirectoryPath).appendingPathComponent("ast.json")
do {
    let enc = JSONEncoder()
    enc.outputFormatting = [.prettyPrinted, .withoutEscapingSlashes]
    try enc.encode(bundle).write(to: outURL, options: .atomic)

} catch {
    fputs("Failed to write ast.json: \(error)\n", stderr)
    exit(1)
}
let diffFolder = rootURL.appendingPathComponent("Swingft_CFF_Dump", isDirectory: true).path
let rc = runSwiftCFF(pyEnvAST: outURL.path, diffOutDir: diffFolder)
if rc != 0 { exit(rc) }

