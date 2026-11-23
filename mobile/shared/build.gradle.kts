plugins {
    kotlin("multiplatform")
    kotlin("plugin.compose")
    id("org.jetbrains.compose")
    id("com.android.kotlin.multiplatform.library")
}

kotlin {
    android {
        namespace = "lab.wallet.shared"
        compileSdk = 37
        minSdk = 24
        withHostTest {}
    }

    listOf(iosArm64(), iosSimulatorArm64()).forEach { target ->
        target.binaries.framework {
            baseName = "WalletShared"
            isStatic = true
        }
    }

    sourceSets {
        commonMain.dependencies {
            implementation("org.jetbrains.compose.runtime:runtime:1.12.2")
            implementation("org.jetbrains.compose.foundation:foundation:1.12.2")
            implementation("org.jetbrains.compose.ui:ui:1.12.2")
            implementation("org.jetbrains.compose.material3:material3:1.9.0")
            implementation("org.jetbrains.kotlinx:kotlinx-coroutines-core:1.11.0")
            implementation("org.jetbrains.kotlinx:kotlinx-serialization-json:1.11.0")
            implementation("io.ktor:ktor-client-core:3.0.1")
        }
        androidMain.dependencies {
            implementation("io.ktor:ktor-client-okhttp:3.0.1")
        }
        iosMain.dependencies {
            implementation("io.ktor:ktor-client-darwin:3.0.1")
        }
        commonTest.dependencies {
            implementation(kotlin("test"))
        }
    }
}
