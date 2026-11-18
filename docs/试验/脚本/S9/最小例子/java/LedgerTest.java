package demo;

import static org.junit.jupiter.api.Assertions.assertEquals;

import java.sql.DriverManager;
import org.junit.jupiter.api.Test;
import org.testcontainers.postgresql.PostgreSQLContainer;

class LedgerTest {
    @Test
    void 记两笔后合计正确() throws Exception {
        try (var pg = new PostgreSQLContainer("postgres:18.6")) {
            pg.start();
            try (var conn = DriverManager.getConnection(pg.getJdbcUrl(), pg.getUsername(), pg.getPassword())) {
                var ledger = new Ledger(conn);
                ledger.init();
                ledger.add(1250, "午饭");
                ledger.add(300, "水");
                assertEquals(1550, ledger.total());
            }
        }
    }
}
