import SwiftUI
import WalletShared

@main
struct WalletLabApp: App {
    var body: some Scene {
        WindowGroup {
            WalletContent().ignoresSafeArea(.container)
        }
    }
}

private struct WalletContent: UIViewControllerRepresentable {
    func makeUIViewController(context: Context) -> UIViewController {
        IosWalletKt.walletViewController()
    }

    func updateUIViewController(_ controller: UIViewController, context: Context) {}
}
