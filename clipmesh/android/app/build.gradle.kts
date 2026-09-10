import org.jetbrains.kotlin.gradle.dsl.JvmTarget

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

val releaseSigningEnvironment = mapOf(
    "CLIPMESH_ANDROID_KEYSTORE_PATH" to System.getenv("CLIPMESH_ANDROID_KEYSTORE_PATH"),
    "CLIPMESH_ANDROID_KEYSTORE_PASSWORD" to System.getenv("CLIPMESH_ANDROID_KEYSTORE_PASSWORD"),
    "CLIPMESH_ANDROID_KEY_ALIAS" to System.getenv("CLIPMESH_ANDROID_KEY_ALIAS"),
    "CLIPMESH_ANDROID_KEY_PASSWORD" to System.getenv("CLIPMESH_ANDROID_KEY_PASSWORD"),
)
val releaseTaskRequested = gradle.startParameter.taskNames.any {
    it.contains("release", ignoreCase = true)
}
if (releaseTaskRequested) {
    val missing = releaseSigningEnvironment.filterValues { it.isNullOrBlank() }.keys
    require(missing.isEmpty()) {
        "Release signing is mandatory. Missing environment variables: ${missing.joinToString(", ")}"
    }
}

android {
    namespace = "dev.clipmesh"
    compileSdk = 36

    defaultConfig {
        applicationId = "dev.clipmesh"
        minSdk = 26
        targetSdk = 36
        versionCode = 21
        versionName = "0.2.11"
    }

    buildFeatures {
        buildConfig = true
        aidl = true
    }

    signingConfigs {
        create("release") {
            releaseSigningEnvironment["CLIPMESH_ANDROID_KEYSTORE_PATH"]
                ?.takeIf { it.isNotBlank() }
                ?.let { storeFile = file(it) }
            storePassword = releaseSigningEnvironment["CLIPMESH_ANDROID_KEYSTORE_PASSWORD"]
            keyAlias = releaseSigningEnvironment["CLIPMESH_ANDROID_KEY_ALIAS"]
            keyPassword = releaseSigningEnvironment["CLIPMESH_ANDROID_KEY_PASSWORD"]
        }
    }

    buildTypes {
        release {
            signingConfig = signingConfigs.getByName("release")
            isMinifyEnabled = true
            isShrinkResources = true
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro"
            )
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
}

dependencies {
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.10.2")
    implementation("dev.rikka.shizuku:api:13.1.5")
    implementation("dev.rikka.shizuku:provider:13.1.5")
}

kotlin {
    compilerOptions {
        jvmTarget.set(JvmTarget.JVM_17)
    }
}
