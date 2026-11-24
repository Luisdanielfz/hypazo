import java.util.Properties

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

// Firma release: android/keystore.properties (fuera de git) apunta al almacén de claves que crea Luigi.
val firma = rootProject.file("keystore.properties").takeIf { it.isFile }?.let { f -> Properties().apply { f.inputStream().use { load(it) } } }

// Lo compartido con el escritorio (fuentes) se copia del repo en cada compilación: sin duplicados en git.
val copiarWeb by tasks.registering(Copy::class) {
    from(rootProject.file("../assets/fonts")) { into("movil/fonts") }
    into(layout.buildDirectory.dir("generated/web"))
}

android {
    namespace = "es.hypazo.movil"
    compileSdk = 36

    defaultConfig {
        applicationId = "es.hypazo.movil"
        minSdk = 29           // Android 10
        targetSdk = 36
        versionCode = 1
        versionName = "0.1.0"
    }

    signingConfigs {
        if (firma != null) create("release") {
            storeFile = rootProject.file(firma.getProperty("storeFile"))
            storePassword = firma.getProperty("storePassword")
            keyAlias = firma.getProperty("keyAlias")
            keyPassword = firma.getProperty("keyPassword")
        }
    }
    buildTypes {
        release {
            isMinifyEnabled = false
            if (firma != null) signingConfig = signingConfigs.getByName("release")
        }
    }
    sourceSets["main"].assets.srcDir(layout.buildDirectory.dir("generated/web"))
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions { jvmTarget = "17" }
}

tasks.named("preBuild") { dependsOn(copiarWeb) }

dependencies {
    implementation("androidx.webkit:webkit:1.12.1")
    implementation("androidx.activity:activity-ktx:1.9.3")
    implementation("com.squareup.okhttp3:okhttp:4.12.0")
    implementation("com.google.android.gms:play-services-code-scanner:16.1.0")   // escanear el QR del PC sin permiso de cámara
    testImplementation("junit:junit:4.13.2")
}
