plugins { id("com.android.application") }
android {
    namespace = "io.github.taobaotasks.assistant"
    compileSdk = 35
    defaultConfig {
        applicationId = "io.github.taobaotasks.assistant"
        minSdk = 28
        targetSdk = 35
        versionCode = 1
        versionName = "0.1.0"
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    testOptions { unitTests.isReturnDefaultValues = true }
    buildTypes { release { isMinifyEnabled = false } }
}
dependencies {
    implementation("com.google.mlkit:text-recognition-chinese:16.0.1")
    testImplementation("junit:junit:4.13.2")
}
