import Foundation

class PlistAnalyzer {
    private let fileManager = FileManager.default
    private let principalClassKeys = [
        "NSPrincipalClass", "NSExtensionPrincipalClass", "UISceneDelegateClassName"
    ]

    // [수정] 반환 타입을 Set<String>으로 변경
    func analyze(projectURL: URL) -> Set<String> {
        var foundClasses = Set<String>()
        let enumerator = fileManager.enumerator(at: projectURL, includingPropertiesForKeys: nil, options: [.skipsHiddenFiles])

        while let fileURL = enumerator?.nextObject() as? URL {
            if fileURL.pathExtension == "plist" {
                guard let plistDict = NSDictionary(contentsOf: fileURL) as? [String: Any] else { continue }

                findClasses(in: plistDict, storage: &foundClasses)
            }
        }
        return foundClasses
    }

    // [추가] 재귀적으로 모든 딕셔너리를 탐색하는 헬퍼 함수
    private func findClasses(in dictionary: [String: Any], storage: inout Set<String>) {
        for (key, value) in dictionary {
            if principalClassKeys.contains(key), let className = value as? String {
                storage.insert(className)
            } else if let subDict = value as? [String: Any] {
                findClasses(in: subDict, storage: &storage)
            } else if let subArray = value as? [[String: Any]] {
                for item in subArray {
                    findClasses(in: item, storage: &storage)
                }
            }
        }
    }
}