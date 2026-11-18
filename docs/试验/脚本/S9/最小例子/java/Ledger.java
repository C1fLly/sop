package demo;

import java.sql.Connection;
import java.sql.SQLException;

/** 最小的业务代码：往数据库里记一笔，再算合计。 */
public final class Ledger {
    private final Connection conn;
    public Ledger(Connection conn) { this.conn = conn; }

    public void init() throws SQLException {
        try (var st = conn.createStatement()) { st.execute("create table if not exists entry(id serial primary key, fen int not null, note text not null)"); }
    }
    public void add(int fen, String note) throws SQLException {
        try (var ps = conn.prepareStatement("insert into entry(fen, note) values (?, ?)")) { ps.setInt(1, fen); ps.setString(2, note); ps.executeUpdate(); }
    }
    public int total() throws SQLException {
        try (var st = conn.createStatement(); var rs = st.executeQuery("select coalesce(sum(fen), 0) from entry")) { rs.next(); return rs.getInt(1); }
    }
}
