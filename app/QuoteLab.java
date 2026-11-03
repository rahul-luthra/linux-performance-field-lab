import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;
import java.io.IOException;
import java.lang.management.ManagementFactory;
import java.lang.management.ThreadMXBean;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.Locale;
import java.util.concurrent.Executors;

/** Tiny, deterministic CPU-bound quote calculation for a loopback-only lab. */
public final class QuoteLab {
    private static final ThreadMXBean THREADS = ManagementFactory.getThreadMXBean();
    private static final int ITERATIONS = 1_200_000;

    static double quote() {
        double total = 0;
        long state = 123456789;
        for (int i = 0; i < ITERATIONS; i++) {
            state = (state * 1664525 + 1013904223) & 0xffffffffL;
            double risk = (state + 1.0) / 4294967296.0;
            total += Math.sqrt(risk) + Math.log1p(risk);
        }
        return 100.0 + total / ITERATIONS;
    }

    static void respond(HttpExchange exchange, int status, String body) throws IOException {
        byte[] bytes = body.getBytes(StandardCharsets.UTF_8);
        exchange.getResponseHeaders().set("Content-Type", "application/json; charset=utf-8");
        exchange.getResponseHeaders().set("Cache-Control", "no-store");
        exchange.sendResponseHeaders(status, bytes.length);
        try (var output = exchange.getResponseBody()) { output.write(bytes); }
    }

    public static void main(String[] args) throws Exception {
        if (THREADS.isThreadCpuTimeSupported() && !THREADS.isThreadCpuTimeEnabled())
            THREADS.setThreadCpuTimeEnabled(true);
        HttpServer server = HttpServer.create(new InetSocketAddress("127.0.0.1", 8087), 32);
        var threadNumber = new java.util.concurrent.atomic.AtomicInteger();
        server.setExecutor(Executors.newFixedThreadPool(2, task -> new Thread(task, "quote-worker-" + threadNumber.getAndIncrement())));
        server.createContext("/", exchange -> {
            try {
                if (!exchange.getRequestMethod().equals("GET")) {
                    respond(exchange, 405, "{\"error\":\"GET required\"}");
                } else if (exchange.getRequestURI().getPath().equals("/health")) {
                    respond(exchange, 200, "{\"status\":\"ok\"}");
                } else if (exchange.getRequestURI().getPath().equals("/quote")) {
                    long start = System.nanoTime();
                    long cpuStart = THREADS.getCurrentThreadCpuTime();
                    double result = quote();
                    double cpuMs = (THREADS.getCurrentThreadCpuTime() - cpuStart) / 1e6;
                    double wallMs = (System.nanoTime() - start) / 1e6;
                    exchange.getResponseHeaders().set("X-Handler-Wall-Ms", String.format(Locale.ROOT, "%.3f", wallMs));
                    exchange.getResponseHeaders().set("X-Handler-Cpu-Ms", String.format(Locale.ROOT, "%.3f", cpuMs));
                    respond(exchange, 200, String.format(Locale.ROOT, "{\"quote\":%.6f,\"iterations\":%d}", result, ITERATIONS));
                } else {
                    respond(exchange, 404, "{\"error\":\"not found\"}");
                }
            } catch (Exception e) {
                exchange.close();
            }
        });
        Runtime.getRuntime().addShutdownHook(new Thread(() -> server.stop(0)));
        server.start();
        System.out.println("QuoteLab listening on loopback port 8087; iterations=" + ITERATIONS);
    }
}
