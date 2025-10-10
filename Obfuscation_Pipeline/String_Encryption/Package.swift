// swift-tools-version: 6.1

import PackageDescription

let package = Package(
    name: "Swingft_Encryption",
    platforms: [.macOS(.v13)],
    dependencies: [
        .package(url: "https://github.com/apple/swift-syntax.git",
                exact: "601.0.1")
    ],
    targets: [
        .executableTarget(
            name: "Swingft_Encryption",
            dependencies: [
                .product(name: "SwiftSyntax", package: "swift-syntax"),
                .product(name: "SwiftParser", package: "swift-syntax")
            ]
        )
    ]
)
