package com.jev.probe.core

import java.net.HttpURLConnection
import java.net.Inet4Address
import java.net.InetSocketAddress
import java.net.NetworkInterface
import java.net.Socket
import java.net.URL
import java.util.Collections
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicReference

/**
 * 在局域网里自动找到 Mac 上的 NanoJev 服务。
 *
 * 为什么需要它：Mac 的局域网地址由路由器 DHCP 分配，换网络、重启路由或
 * 从无线切到有线，地址都会变（实测一天内变了两次）。手动填地址对非技术
 * 用户不友好，所以这里直接扫本机所在 /24 网段，命中 /health 的那个就是。
 *
 * 实现要点：
 *  - 先用 TCP connect（260ms）快速筛掉不存在的地址，再对存活的做一次
 *    HTTP /health 确认，避免 254 个 HTTP 超时把总耗时拖到分钟级。
 *  - 64 并发，单轮通常 2–6 秒出结果。
 */
object LocalDiscovery {

    /** 常见的局域网私有网段判断。 */
    private fun isPrivate(ip: String): Boolean =
        ip.startsWith("192.168.") ||
            ip.startsWith("10.") ||
            ip.startsWith("172.16.") || ip.startsWith("172.17.") ||
            ip.startsWith("172.18.") || ip.startsWith("172.19.") ||
            ip.startsWith("172.2") || ip.startsWith("172.30.") || ip.startsWith("172.31.")

    /**
     * 取本机在局域网里的 IPv4 地址，用于推导网段。
     * 拿不到时返回 null（通常是 WiFi 没连或只开了流量）。
     */
    fun localIpv4(): String? {
        try {
            for (nif in Collections.list(NetworkInterface.getNetworkInterfaces())) {
                if (!nif.isUp || nif.isLoopback) continue
                for (addr in Collections.list(nif.inetAddresses)) {
                    if (addr !is Inet4Address || addr.isLoopbackAddress) continue
                    val ip = addr.hostAddress ?: continue
                    if (isPrivate(ip)) return ip
                }
            }
        } catch (_: Exception) {
            // 某些 ROM 会限制网卡枚举，静默降级
        }
        return null
    }

    /** 确认某个地址后面真的是 NanoJev 服务（而不是同网段的其它设备）。 */
    fun probe(base: String, timeoutMs: Int = 1200): Boolean {
        var conn: HttpURLConnection? = null
        return try {
            conn = (URL("$base/health").openConnection() as HttpURLConnection).apply {
                requestMethod = "GET"
                connectTimeout = timeoutMs
                readTimeout = timeoutMs
            }
            conn.responseCode in 200..299
        } catch (_: Exception) {
            false
        } finally {
            try { conn?.disconnect() } catch (_: Exception) { }
        }
    }

    private fun tcpAlive(host: String, port: Int, timeoutMs: Int): Boolean = try {
        Socket().use { it.connect(InetSocketAddress(host, port), timeoutMs) }
        true
    } catch (_: Exception) {
        false
    }

    /**
     * 扫描本机所在 /24 网段，返回第一个命中的服务地址（形如
     * "http://192.168.1.10:8788"）；找不到返回 null。
     *
     * @param port     NanoJev 服务端口，默认 8788
     * @param budgetMs 总预算。超时即返回已找到的结果（可能为 null）
     */
    fun scan(port: Int = 8788, budgetMs: Long = 20000): String? {
        val myIp = localIpv4() ?: return null
        val prefix = myIp.substringBeforeLast('.')
        val hosts = (1..254).map { "$prefix.$it" }

        val found = AtomicReference<String?>(null)
        val latch = CountDownLatch(hosts.size)
        val pool = Executors.newFixedThreadPool(64)
        val deadline = System.currentTimeMillis() + budgetMs

        for (h in hosts) {
            pool.execute {
                try {
                    if (found.get() != null || System.currentTimeMillis() > deadline) return@execute
                    if (tcpAlive(h, port, 260)) {
                        val base = "http://$h:$port"
                        if (probe(base, 1500)) found.compareAndSet(null, base)
                    }
                } catch (_: Exception) {
                    // 单个地址失败不影响整体
                } finally {
                    latch.countDown()
                }
            }
        }

        try {
            latch.await(budgetMs + 4000, TimeUnit.MILLISECONDS)
        } catch (_: Exception) {
        }
        pool.shutdownNow()
        return found.get()
    }
}
