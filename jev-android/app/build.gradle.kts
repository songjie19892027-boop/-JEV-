import java.util.Properties

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "com.jev.probe"
    compileSdk = 35

    defaultConfig {
        applicationId = "com.jev.probe"
        minSdk = 30
        targetSdk = 35
        versionCode = 1
        versionName = "1.0"
    }

    // 密钥库路径与口令从 local.properties（不入库）或环境变量读取，
    // 仓库里不保存任何口令；未配置时 release 构建保持未签名。
    //   local.properties:
    //     jev.storeFile=jev-release.jks
    //     jev.storePassword=<口令>
    //     jev.keyAlias=jevkey
    //     jev.keyPassword=<口令>
    //   或环境变量：JEV_STORE_FILE / JEV_STORE_PASSWORD / JEV_KEY_ALIAS / JEV_KEY_PASSWORD
    val signProps = Properties().apply {
        val f = rootProject.file("local.properties")
        if (f.exists()) f.inputStream().use { load(it) }
    }
    fun signValue(propKey: String, envKey: String): String =
        signProps.getProperty(propKey)?.takeIf { it.isNotBlank() }
            ?: System.getenv(envKey)?.takeIf { it.isNotBlank() }
            ?: ""

    val releaseStorePath = signValue("jev.storeFile", "JEV_STORE_FILE")

    signingConfigs {
        if (releaseStorePath.isNotBlank()) {
            create("release") {
                storeFile = rootProject.file(releaseStorePath)
                storePassword = signValue("jev.storePassword", "JEV_STORE_PASSWORD")
                keyAlias = signValue("jev.keyAlias", "JEV_KEY_ALIAS")
                keyPassword = signValue("jev.keyPassword", "JEV_KEY_PASSWORD")
            }
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            isShrinkResources = false
            // 只在密钥库已配置时才挂签名，便于他人 clone 后直接构建。
            signingConfigs.findByName("release")?.let { signingConfig = it }
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlinOptions {
        jvmTarget = "17"
    }
}

dependencies {
    implementation("androidx.core:core-ktx:1.13.1")
    implementation("androidx.appcompat:appcompat:1.7.0")
    implementation("com.google.android.material:material:1.12.0")
    implementation("androidx.constraintlayout:constraintlayout:2.1.4")
}
