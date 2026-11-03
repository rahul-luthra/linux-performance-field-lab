import com.sun.net.httpserver.*;
import java.io.*;
import java.lang.management.*;
import java.net.*;
import java.nio.*;
import java.nio.charset.StandardCharsets;
import java.util.*;
import java.util.concurrent.*;

/** Bounded fault-injection teaching service; bind loopback and run inside a memory cgroup. */
public final class MemoryLab {
    static final int MIB = 1024 * 1024;
    static final List<Object> LIVE = new ArrayList<>();
    static final ThreadLocal<byte[]> REUSABLE = ThreadLocal.withInitial(() -> new byte[MIB]);
    static final ThreadMXBean THREADS = ManagementFactory.getThreadMXBean();
    static volatile String strategy = "quiet";
    static volatile int retainedMiB;
    static volatile boolean allocationComplete;
    static volatile byte[] escaped;

    static long gcCount() { return ManagementFactory.getGarbageCollectorMXBeans().stream().mapToLong(b -> Math.max(0, b.getCollectionCount())).sum(); }
    static long gcMillis() { return ManagementFactory.getGarbageCollectorMXBeans().stream().mapToLong(b -> Math.max(0, b.getCollectionTime())).sum(); }
    static void respond(HttpExchange x, int status, String body) throws IOException {
        byte[] bytes = body.getBytes(StandardCharsets.UTF_8);
        x.getResponseHeaders().set("Content-Type", "application/json");
        x.getResponseHeaders().set("Cache-Control", "no-store");
        x.sendResponseHeaders(status, bytes.length);
        try (var out = x.getResponseBody()) { out.write(bytes); }
    }
    static String metrics() {
        var heap = ManagementFactory.getMemoryMXBean().getHeapMemoryUsage();
        return String.format(Locale.ROOT, "{\"heap_used\":%d,\"heap_committed\":%d,\"heap_max\":%d,\"gc_count\":%d,\"gc_ms\":%d,\"retained_mib\":%d,\"allocation_complete\":%s,\"strategy\":\"%s\"}",
                heap.getUsed(), heap.getCommitted(), heap.getMax(), gcCount(), gcMillis(), retainedMiB, allocationComplete, strategy);
    }
    static long scratch() {
        if (strategy.equals("quiet")) return 0;
        boolean reuse = strategy.equals("reuse");
        byte[] buffer = reuse ? REUSABLE.get() : null;
        long checksum = 0;
        // Both modes clear and touch 64 MiB per request; reuse retains one 1-MiB buffer per worker.
        for (int block = 0; block < 64; block++) {
            if (reuse) Arrays.fill(buffer, (byte) 0); else buffer = new byte[MIB];
            for (int offset = 0; offset < buffer.length; offset += 4096) {
                buffer[offset] = 7;
                checksum += buffer[offset];
            }
            escaped = buffer; // Make allocation observable and prevent scalar replacement.
        }
        return checksum;
    }
    public static void main(String[] args) throws Exception {
        String mode = args.length == 0 ? "pressure" : args[0];
        if (!Set.of("pressure", "heap", "direct").contains(mode)) throw new IllegalArgumentException("unknown mode");
        if (THREADS.isThreadCpuTimeSupported() && !THREADS.isThreadCpuTimeEnabled()) THREADS.setThreadCpuTimeEnabled(true);
        if (mode.equals("pressure")) {
            for (int i = 0; i < 16; i++) { LIVE.add(new byte[MIB]); retainedMiB++; }
            allocationComplete = true;
        }
        HttpServer server = HttpServer.create(new InetSocketAddress("127.0.0.1", 8088), 16);
        var threadNumber = new java.util.concurrent.atomic.AtomicInteger();
        var executor = Executors.newFixedThreadPool(2, task -> new Thread(task, "memory-http-" + threadNumber.getAndIncrement()));
        server.setExecutor(executor);
        server.createContext("/", x -> {
            try {
                String path = x.getRequestURI().getPath();
                if (!x.getRequestMethod().equals("GET")) { respond(x, 405, "{\"error\":\"GET required\"}"); }
                else if (path.equals("/metrics") || path.equals("/health")) { respond(x, 200, metrics()); }
                else if (path.equals("/mode")) {
                    String query = x.getRequestURI().getRawQuery();
                    String next = query != null && query.startsWith("value=") ? query.substring(6) : "";
                    if (!mode.equals("pressure") || !Set.of("quiet", "allocate", "reuse").contains(next)) respond(x, 400, "{\"error\":\"invalid mode\"}");
                    else { strategy = next; respond(x, 200, metrics()); }
                } else if (path.equals("/quote")) {
                    long start = System.nanoTime(), cpu = THREADS.getCurrentThreadCpuTime();
                    double quote = QuoteLab.quote();
                    long checksum = scratch();
                    x.getResponseHeaders().set("X-Handler-Wall-Ms", String.format(Locale.ROOT, "%.3f", (System.nanoTime() - start) / 1e6));
                    x.getResponseHeaders().set("X-Handler-Cpu-Ms", String.format(Locale.ROOT, "%.3f", (THREADS.getCurrentThreadCpuTime() - cpu) / 1e6));
                    respond(x, 200, String.format(Locale.ROOT, "{\"quote\":%.6f,\"checksum\":%d}", quote, checksum));
                } else respond(x, 404, "{\"error\":\"not found\"}");
            } catch (IOException e) { x.close(); }
        });
        Runtime.getRuntime().addShutdownHook(new Thread(() -> { server.stop(0); executor.shutdownNow(); }));
        server.start();
        System.out.println("READY mode=" + mode + " java=" + System.getProperty("java.version"));
        if (!mode.equals("pressure")) new Thread(() -> {
            try {
                Thread.sleep(5000);
                int target = mode.equals("heap") ? 48 : 80, step = mode.equals("heap") ? 2 : 4;
                while (retainedMiB < target) {
                    if (mode.equals("heap")) LIVE.add(new byte[step * MIB]);
                    else {
                        ByteBuffer direct = ByteBuffer.allocateDirect(step * MIB);
                        for (int offset = 0; offset < direct.capacity(); offset += 4096) direct.put(offset, (byte) 1);
                        LIVE.add(direct);
                    }
                    retainedMiB += step;
                    System.out.println("RETAINED_MIB=" + retainedMiB);
                    Thread.sleep(250);
                }
                allocationComplete = true;
                System.out.println("ALLOCATION_COMPLETE retained_mib=" + retainedMiB);
            } catch (InterruptedException e) { Thread.currentThread().interrupt(); }
        }, "bounded-allocator").start();
    }
}
