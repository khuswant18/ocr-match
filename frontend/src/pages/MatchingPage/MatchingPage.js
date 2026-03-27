import { useState, useEffect, useCallback } from "react";
import {
  Button,
  Autocomplete,
  TextField,
  CircularProgress,
  Paper,
  Typography,
  Chip,
} from "@mui/material";
import { DataGrid } from "@mui/x-data-grid";
import CompareArrowsIcon from "@mui/icons-material/CompareArrows";
import CheckCircleIcon from "@mui/icons-material/CheckCircle";
import ErrorOutlineIcon from "@mui/icons-material/ErrorOutline";
import PlayArrowIcon from "@mui/icons-material/PlayArrow";
import AppLayout from "../../components/AppLayout/AppLayout";
import httpRequest from "../../httpRequest";
import { useStyles } from "./styles";

const BACKEND_URL =
  process.env.REACT_APP_BACKEND_URL || "http://localhost:5001";

// UPGRADED COLUMNS: Now mapping to the exact variance fields from the backend
const COLUMNS = [
  { field: "product_code", headerName: "Product Code", flex: 1, minWidth: 120 },
  {
    field: "po_qty",
    headerName: "PO Qty",
    flex: 0.6,
    minWidth: 80,
    type: "number",
  },
  {
    field: "grn_qty",
    headerName: "GRN Qty",
    flex: 0.6,
    minWidth: 80,
    type: "number",
  },
  {
    field: "invoice_qty",
    headerName: "Inv Qty",
    flex: 0.6,
    minWidth: 80,
    type: "number",
  },
  {
    field: "qty_variance",
    headerName: "Qty Var",
    flex: 0.7,
    minWidth: 90,
    type: "number",
    renderCell: (params) => {
      const val = params.value;
      if (!val) return "-";
      return (
        <span
          style={{ color: val > 0 ? "#d32f2f" : "#2e7d32", fontWeight: "bold" }}
        >
          {val > 0 ? `+{val}` : val}
        </span>
      );
    },
  },
  {
    field: "po_price",
    headerName: "PO Price",
    flex: 0.8,
    minWidth: 100,
    type: "number",
    valueFormatter: (params) => params.value?.toFixed(2),
  },
  {
    field: "invoice_price",
    headerName: "Inv Price",
    flex: 0.8,
    minWidth: 100,
    type: "number",
    valueFormatter: (params) => params.value?.toFixed(2),
  },
  {
    field: "price_variance",
    headerName: "Price Var",
    flex: 0.8,
    minWidth: 100,
    type: "number",
    renderCell: (params) => {
      const val = params.value;
      if (!val || Math.abs(val) <= 0.05) return "-"; // Ignoring tiny rounding errors
      return (
        <span style={{ color: "#d32f2f", fontWeight: "bold" }}>
          {val > 0 ? `+${val.toFixed(2)}` : `-${Math.abs(val).toFixed(2)}`}
        </span>
      );
    },
  },
  {
    field: "status",
    headerName: "Status",
    flex: 1,
    minWidth: 130,
    renderCell: (params) => {
      if (params.value === "matched")
        return <Chip label="Matched" color="success" size="small" />;
      if (params.value === "not_on_po")
        return <Chip label="Not on PO" color="warning" size="small" />;
      return <Chip label="Mismatch" color="error" size="small" />;
    },
  },
  {
    field: "issue_summary",
    headerName: "Issue Details",
    flex: 2,
    minWidth: 250,
  },
];

const RAW_PO_COLUMNS = [
  { field: "product_code", headerName: "Product Code", flex: 1, minWidth: 120 },
  { field: "qty", headerName: "PO Qty", flex: 0.8, minWidth: 100, type: "number" },
  { field: "price", headerName: "PO Price", flex: 0.8, minWidth: 100, type: "number", valueFormatter: (params) => params.value?.toFixed(2) },
  { field: "desc", headerName: "Description", flex: 2, minWidth: 250 },
];

const RAW_INV_COLUMNS = [
  { field: "product_code", headerName: "Product Code", flex: 1, minWidth: 120 },
  { field: "desc", headerName: "Item Name / Description", flex: 2, minWidth: 200 },
  { field: "qty", headerName: "Invoice Qty", flex: 0.8, minWidth: 100, type: "number" },
  { field: "price", headerName: "Invoice Price", flex: 0.8, minWidth: 100, type: "number", valueFormatter: (params) => params.value?.toFixed(2) },
  { field: "total", headerName: "Total", flex: 0.8, minWidth: 100, type: "number", valueFormatter: (params) => params.value?.toFixed(2) },
];

const RAW_GRN_COLUMNS = [
  { field: "product_code", headerName: "Product Code", flex: 1, minWidth: 120 },
  { field: "grn_number", headerName: "GRN Number", flex: 1, minWidth: 120 },
  { field: "qty", headerName: "Received Qty", flex: 0.8, minWidth: 100, type: "number" },
];

const MatchingPage = () => {
  const classes = useStyles();
  const [poList, setPoList] = useState([]);
  const [selectedPo, setSelectedPo] = useState("");
  const [loading, setLoading] = useState(false);
  const [loadingPoList, setLoadingPoList] = useState(true);
  const [result, setResult] = useState(null); // Now expects { matches: [...] }
  const [rawPoItems, setRawPoItems] = useState(null);
  const [rawInvItems, setRawInvItems] = useState(null);
  const [rawGrnItems, setRawGrnItems] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    const fetchPoList = async () => {
      try {
        const res = await httpRequest.get(`${BACKEND_URL}/api/match/po-list`);
        console.log("res1", res.data);
        setPoList(res.data);
      } catch (err) {
        console.error("Failed to fetch PO list:", err);
      } finally {
        setLoadingPoList(false);
      }
    };
    fetchPoList();
  }, []);

  const runMatch = useCallback(async () => {
    if (!selectedPo) return;
    setLoading(true);
    setResult(null);
    setError(null);
    try {
      const res = await httpRequest.get(
        `${BACKEND_URL}/api/match/${selectedPo}`,
      );
      console.log("res2", res.data);

      if (res.data.error) {
        setError(res.data.error);
      } else {
        setResult(res.data.matches || []);
        setRawPoItems(res.data.raw_po_items || []);
        setRawInvItems(res.data.raw_inv_items || []);
        setRawGrnItems(res.data.raw_grn_items || []);
      } 
    } catch (err) {
      const msg = err.response?.data?.error || err.message;
      setError(msg);
    } finally {
      setLoading(false);
    }
  }, [selectedPo]);

  const totalItems = result ? result.length : 0;
  const priceErrors = result
    ? result.filter((r) => !r.is_price_match).length
    : 0;
  const qtyErrors = result ? result.filter((r) => !r.is_qty_match).length : 0;
  const perfectMatches = result
    ? result.filter((r) => r.status === "matched").length
    : 0;

  const selectedPoData = poList.find((p) => p.po_number === selectedPo);

  return (
    <AppLayout userName="Demo User">
      <div className={classes.content}>
        <div className={classes.header}>
          <Typography className={classes.title}>
            <CompareArrowsIcon
              sx={{
                fontSize: 32,
                verticalAlign: "middle",
                mr: 1,
                color: "#854de0",
              }}
            />
            Three-Way Match Engine
          </Typography>
          <Typography className={classes.subtitle}>
            Compare Purchase Order → Goods Receipt → Invoice
          </Typography>
        </div>

        <div className={classes.selectorRow}>
          <Autocomplete
            freeSolo
            id="po-selector"
            className={classes.selectField}
            options={poList.map((po) => po.po_number)}
            value={selectedPo}
            onInputChange={(e, val) => {
              setSelectedPo(val || "");
              setResult(null);
              setRawPoItems(null);
              setRawInvItems(null);
              setRawGrnItems(null);
              setError(null);
            }}
            onChange={(e, val) => {
              setSelectedPo(val || "");
              setResult(null);
              setRawPoItems(null);
              setRawInvItems(null);
              setRawGrnItems(null);
              setError(null);
            }}
            renderInput={(params) => (
              <TextField
                {...params}
                label="Purchase Order"
                variant="outlined"
                InputProps={{
                  ...params.InputProps,
                  endAdornment: (
                    <>
                      {loadingPoList ? (
                        <CircularProgress color="inherit" size={20} />
                      ) : null}
                      {params.InputProps.endAdornment}
                    </>
                  ),
                }}
              />
            )}
          />

          <Button
            variant="contained"
            className={classes.matchButton}
            onClick={runMatch}
            disabled={!selectedPo || loading}
            startIcon={
              loading ? (
                <CircularProgress size={20} color="inherit" />
              ) : (
                <PlayArrowIcon />
              )
            }
          >
            {loading ? "Processing..." : "Run Match"}
          </Button>
        </div>

        {selectedPoData && (
          <div className={classes.poInfo}>
            <div className={classes.poInfoItem}>
              <span className={classes.poInfoLabel}>PO Number:</span>{" "}
              {selectedPoData.po_number}
            </div>
            <div className={classes.poInfoItem}>
              <span className={classes.poInfoLabel}>Date:</span>{" "}
              {selectedPoData.po_date}
            </div>
          </div>
        )}

        {error && (
          <div className={classes.errorBanner}>
            <ErrorOutlineIcon sx={{ color: "#c62828", fontSize: 32, mr: 1 }} />
            <Typography sx={{ color: "#c62828", fontWeight: 600 }}>
              {error}
            </Typography>
          </div>
        )}

        {loading && (
          <div className={classes.loader}>
            <CircularProgress size={48} sx={{ color: "#854de0" }} />
          </div>
        )}

        {result && !loading && (
          <>
            <div className={classes.summaryGrid}>
              <div className={classes.summaryCard}>
                <Typography sx={{ color: "#666" }}>Total Line Items</Typography>
                <Typography variant="h4">{totalItems}</Typography>
              </div>
              <div
                className={classes.summaryCard}
                style={{
                  backgroundColor:
                    priceErrors > 0 ? "rgba(211, 47, 47, 0.1)" : "inherit",
                }}
              >
                <Typography
                  sx={{ color: priceErrors > 0 ? "#d32f2f" : "#666" }}
                >
                  Price Overcharges
                </Typography>
                <Typography
                  variant="h4"
                  sx={{ color: priceErrors > 0 ? "#d32f2f" : "inherit" }}
                >
                  {priceErrors}
                </Typography>
              </div>
              <div
                className={classes.summaryCard}
                style={{
                  backgroundColor:
                    qtyErrors > 0 ? "rgba(255, 152, 0, 0.1)" : "inherit",
                }}
              >
                <Typography sx={{ color: qtyErrors > 0 ? "#ed6c02" : "#666" }}>
                  Quantity Overbills
                </Typography>
                <Typography
                  variant="h4"
                  sx={{ color: qtyErrors > 0 ? "#ed6c02" : "inherit" }}
                >
                  {qtyErrors}
                </Typography>
              </div>
              <div
                className={classes.summaryCard}
                style={{ backgroundColor: "rgba(46, 125, 50, 0.1)" }}
              >
                <Typography sx={{ color: "#2e7d32" }}>
                  Perfect Matches
                </Typography>
                <Typography variant="h4" sx={{ color: "#2e7d32" }}>
                  {perfectMatches}
                </Typography>
              </div>
            </div>

            {totalItems > 0 && perfectMatches === totalItems && (
              <div className={classes.matchedBanner}>
                <CheckCircleIcon
                  sx={{ color: "#2e7d32", fontSize: 40, mr: 2 }}
                />
                <Typography
                  sx={{ color: "#2e7d32", fontWeight: 700, fontSize: "1.2rem" }}
                >
                  All items matched perfectly — No discrepancies found!
                </Typography>
              </div>
            )}

            {totalItems > 0 && (
              <Paper
                className={classes.tableContainer}
                elevation={3}
                sx={{ mt: 3, p: 2 }}
              >
                <Typography
                  variant="h6"
                  sx={{ mb: 2, fontWeight: 600, color: "#333" }}
                >
                  Line Item Audit Report
                </Typography>
                <DataGrid
                  // Pass the flat result array directly. Add a unique 'id' for the DataGrid.
                  rows={result.map((row, index) => ({ id: index, ...row }))}
                  columns={COLUMNS}
                  pageSize={10}
                  rowsPerPageOptions={[10, 25, 50]}
                  autoHeight
                  disableSelectionOnClick
                />
              </Paper>
            )}


            {rawPoItems && rawPoItems.length > 0 && (
              <Paper
                className={classes.tableContainer}
                elevation={3}
                sx={{ mt: 3, p: 2 }}
              >
                <Typography
                  variant="h6"
                  sx={{ mb: 2, fontWeight: 600, color: "#333" }}
                >
                  Original PO Line Items
                </Typography>
                <DataGrid
                  rows={rawPoItems.map((row, index) => ({ id: index, ...row }))}
                  columns={RAW_PO_COLUMNS}
                  pageSize={10}
                  rowsPerPageOptions={[10, 25, 50]}
                  autoHeight
                  disableSelectionOnClick
                />
              </Paper>
            )}


            {rawInvItems && rawInvItems.length > 0 && (
              <Paper
                className={classes.tableContainer}
                elevation={3}
                sx={{ mt: 3, p: 2 }}
              >
                <Typography
                  variant="h6"
                  sx={{ mb: 2, fontWeight: 600, color: "#333" }}
                >
                  Extracted Invoice Items
                </Typography>
                <DataGrid
                  rows={rawInvItems.map((row, index) => ({ id: index, ...row }))}
                  columns={RAW_INV_COLUMNS}
                  pageSize={10}
                  rowsPerPageOptions={[10, 25, 50]}
                  autoHeight
                  disableSelectionOnClick
                />
              </Paper>
            )}


            {rawGrnItems && rawGrnItems.length > 0 && (
              <Paper
                className={classes.tableContainer}
                elevation={3}
                sx={{ mt: 3, p: 2 }}
              >
                <Typography
                  variant="h6"
                  sx={{ mb: 2, fontWeight: 600, color: "#333" }}
                >
                  Goods Received Notes (GRN)
                </Typography>
                <DataGrid
                  rows={rawGrnItems.map((row, index) => ({ id: index, ...row }))}
                  columns={RAW_GRN_COLUMNS}
                  pageSize={10}
                  rowsPerPageOptions={[10, 25, 50]}
                  autoHeight
                  disableSelectionOnClick
                />
              </Paper>
            )}
          </>
        )}
      </div>
    </AppLayout>
  );
};

export default MatchingPage;
