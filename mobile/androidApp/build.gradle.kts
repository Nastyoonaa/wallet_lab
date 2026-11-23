plugins {
    id("com.android.application")
    kotlin("plugin.compose")
}

android {
    namespace = "lab.wallet.android"
    compileSdk = 37
    defaultConfig {
        applicationId = "lab.wallet.android"
        minSdk = 24
        targetSdk = 36
        versionCode = 1
        versionName = "0.1.0"
    }
}

dependencies {
    implementation(project(":shared"))
    implementation("androidx.activity:activity-compose:1.13.0")
}
