import at.forsyte.apalache.io.lir.PrettyWriter;
import at.forsyte.apalache.io.quint.Quint;
import at.forsyte.apalache.io.quint.QuintOutput;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import scala.collection.immutable.List$;
import scala.jdk.javaapi.CollectionConverters;
import ujson.Readable;

// In-process converter from the pinned Apalache distribution, without a server.
class Translate {
    public static void main(String[] args) throws Exception {
        var ir = QuintOutput.read(Readable.fromString(Files.readString(Path.of(args[0])))).get();
        var module = new Quint(ir).tlaModule(ir.modules().head()).get();
        var standard = List.of("Integers", "Sequences", "FiniteSets", "TLC", "Apalache", "Variants");
        Files.writeString(Path.of(args[1]), PrettyWriter.writeAsString(module,
            List$.MODULE$.from(CollectionConverters.asScala(standard))));
        var names = module.varDeclarations().iterator();
        while (names.hasNext()) System.out.println(names.next().name());
    }
}
