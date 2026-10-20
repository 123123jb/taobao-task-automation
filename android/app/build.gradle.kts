import java.util.Properties

plugins { id("com.android.application") }

// Resolve directory junctions before looking outside the Android project on Windows.
val androidDirectory = rootProject.projectDir.toPath().toRealPath().toFile()
val localSigning = androidDirectory.resolve("../.android-signing/signing.properties")
val signing = Properties().apply { if (localSigning.isFile) localSigning.inputStream().use { load(it) } }
android {
    namespace = "io.github.taobaotasks.assistant"
    compileSdk = 35
    defaultConfig {
        applicationId = "io.github.taobaotasks.assistant"
        minSdk = 28
        targetSdk = 35
        versionCode = 1
        versionName = "0.1.0-alpha1"
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    testOptions { unitTests.isReturnDefaultValues = true }
    signingConfigs {
        if (localSigning.isFile) create("localRelease") {
            storeFile = androidDirectory.resolve(signing.getProperty("storeFile")).canonicalFile
            storePassword = androidDirectory.resolve(signing.getProperty("passwordFile")).readText().trim()
            keyAlias = signing.getProperty("keyAlias")
            keyPassword = storePassword
        }
    }
    buildTypes {
        release {
            isMinifyEnabled = false
            if (localSigning.isFile) signingConfig = signingConfigs.getByName("localRelease")
        }
    }
}
dependencies {
    implementation("com.google.mlkit:text-recognition-chinese:16.0.1")
    testImplementation("junit:junit:4.13.2")
}
