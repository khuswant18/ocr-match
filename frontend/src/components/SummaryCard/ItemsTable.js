import { Paper, Table, TableBody, TableCell, TableContainer, TableHead, TableRow, Typography } from "@mui/material";

const formatNumber = (val) => {
  const num = Number(val);
  if (isNaN(num) || num === 0) return "—";
  return num.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
};

const ItemsTable = ({ data }) => {
  const items = data?.items || [];

  if (items.length === 0) return null;

  return (
    <TableContainer component={Paper} elevation={3} sx={{ mt: 2, p: 1, borderRadius: 5 }}>
      <Typography variant="h6" sx={{ p: 1, ml: 1, fontWeight: "bold" }}>Items</Typography>
      <Table size="small">
        <TableHead>
          <TableRow>
            <TableCell sx={{ fontWeight: "bold" }}>Description</TableCell>
            <TableCell align="center" sx={{ fontWeight: "bold" }}>UOM</TableCell>
            <TableCell align="right" sx={{ fontWeight: "bold" }}>Qty</TableCell>
            <TableCell align="right" sx={{ fontWeight: "bold" }}>Unit Price</TableCell>
            <TableCell align="right" sx={{ fontWeight: "bold" }}>Total Price</TableCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {items.map((item, index) => (
            <TableRow key={index}>
              <TableCell component="th" scope="row">{item.description || "—"}</TableCell>
              <TableCell align="center">{item.uom || "—"}</TableCell>
              <TableCell align="right">{item.quantity || "—"}</TableCell>
              <TableCell align="right">{formatNumber(item.unit_price)}</TableCell>
              <TableCell align="right">{formatNumber(item.total_price)}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </TableContainer>
  );
};

export default ItemsTable;
