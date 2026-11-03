import com.sun.net.httpserver.*;
import java.io.*;
import java.lang.management.*;
import java.net.*;
import java.nio.*;
import java.nio.channels.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.util.*;
import java.util.concurrent.*;
import java.util.zip.CRC32;

/** Bounded 16-MiB ring file; acknowledge each 64-KiB write only after force(false). */
public final class StorageLab {
    static final int BLOCK = 65536, SLOTS = 256;
    static final ThreadMXBean THREADS = ManagementFactory.getThreadMXBean();
    static long sequence;
    public static void main(String[] args) throws Exception {
        Path file = Path.of(args[0]);
        Files.createDirectories(file.getParent());
        FileChannel channel = FileChannel.open(file, StandardOpenOption.CREATE_NEW, StandardOpenOption.READ, StandardOpenOption.WRITE);
        byte[] initial = new byte[BLOCK];
        for (int i=0; i<SLOTS; i++) { ByteBuffer b=ByteBuffer.wrap(initial); while(b.hasRemaining()) channel.write(b); }
        channel.force(false);
        HttpServer server=HttpServer.create(new InetSocketAddress("127.0.0.1",8089),16);
        var number=new java.util.concurrent.atomic.AtomicInteger();
        var executor=Executors.newFixedThreadPool(2,r->new Thread(r,"storage-http-"+number.getAndIncrement()));
        server.setExecutor(executor);
        server.createContext("/",x->{
            try {
                if(!x.getRequestMethod().equals("GET")) { respond(x,405,"{\"error\":\"GET required\"}"); return; }
                if(x.getRequestURI().getPath().equals("/health")) { respond(x,200,"{\"status\":\"ok\"}"); return; }
                if(!x.getRequestURI().getPath().equals("/save")) { respond(x,404,"{\"error\":\"not found\"}"); return; }
                long began=System.nanoTime(), cpu=THREADS.getCurrentThreadCpuTime();
                long id; int slot; double writeMs,forceMs; long checksum;
                synchronized(channel) {
                    id=sequence++; slot=(int)(id%SLOTS);
                    byte[] payload=new byte[BLOCK]; Arrays.fill(payload,(byte)0x5a);
                    ByteBuffer.wrap(payload).putLong(id);
                    CRC32 crc=new CRC32(); crc.update(payload); checksum=crc.getValue();
                    ByteBuffer bytes=ByteBuffer.wrap(payload);
                    long writeStart=System.nanoTime();
                    channel.position((long)slot*BLOCK); while(bytes.hasRemaining())channel.write(bytes);
                    writeMs=(System.nanoTime()-writeStart)/1e6;
                    long forceStart=System.nanoTime(); channel.force(false); forceMs=(System.nanoTime()-forceStart)/1e6;
                }
                x.getResponseHeaders().set("X-Write-Ms",String.format(Locale.ROOT,"%.3f",writeMs));
                x.getResponseHeaders().set("X-Force-Ms",String.format(Locale.ROOT,"%.3f",forceMs));
                x.getResponseHeaders().set("X-Handler-Wall-Ms",String.format(Locale.ROOT,"%.3f",(System.nanoTime()-began)/1e6));
                x.getResponseHeaders().set("X-Handler-Cpu-Ms",String.format(Locale.ROOT,"%.3f",(THREADS.getCurrentThreadCpuTime()-cpu)/1e6));
                respond(x,200,String.format(Locale.ROOT,"{\"sequence\":%d,\"slot\":%d,\"saved_bytes\":%d,\"crc32\":%d}",id,slot,BLOCK,checksum));
            }catch(IOException e){x.close();}
        });
        Runtime.getRuntime().addShutdownHook(new Thread(()->{server.stop(0);executor.shutdownNow();try{channel.close();}catch(IOException ignored){}}));
        server.start(); System.out.println("READY bounded_bytes="+(BLOCK*SLOTS));
    }
    static void respond(HttpExchange x,int status,String body)throws IOException {
        byte[] bytes=body.getBytes(StandardCharsets.UTF_8); x.getResponseHeaders().set("Content-Type","application/json");
        x.getResponseHeaders().set("Cache-Control","no-store");x.sendResponseHeaders(status,bytes.length);
        try(var out=x.getResponseBody()){out.write(bytes);}
    }
}
