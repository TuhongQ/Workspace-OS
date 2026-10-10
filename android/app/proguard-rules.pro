# smbj 依赖反射加载（事件总线、SPI、SMB2 指令映射），整体保留避免运行期崩溃
-keep class com.hierynomus.** { *; }
-keep class net.engio.mbassy.** { *; }
-dontwarn net.engio.mbassy.**
-dontwarn org.slf4j.**
-dontwarn javax.naming.**
-dontwarn java.beans.**
-dontwarn com.hierynomus.**

# BouncyCastle（SMB 签名协商按需加载）
-keep class org.bouncycastle.** { *; }
-dontwarn org.bouncycastle.**
-dontwarn org.junit.**

# Kotlin/Compose 元数据
-keepattributes RuntimeVisibleAnnotations,AnnotationDefault,Signature,InnerClasses,EnclosingMethod
-keep class kotlin.Metadata { *; }
-dontwarn kotlin.**
