import { useState, useEffect, useCallback } from "react";
import {
  Button,
  FormControl,
  InputLabel,
  Select,
  MenuItem,
  Autocomplete,
  TextField,
  CircularProgress,
  Paper,
  Typography,
} from "@mui/material";
import { DataGrid } from "@mui/x-data-grid";
import CompareArrowsIcon from "@mui/icons-material/CompareArrows";
import CheckCircleIcon from "@mui/icons-material/CheckCircle";
import ErrorOutlineIcon from "@mui/icons-material/ErrorOutline";
import WarningAmberIcon from "@mui/icons-material/WarningAmber";
import RemoveCircleOutlineIcon from "@mui/icons-material/RemoveCircleOutline";
import AddCircleOutlineIcon from "@mui/icons-material/AddCircleOutline";
import LocalShippingIcon from "@mui/icons-material/LocalShipping";
import ReceiptIcon from "@mui/icons-material/Receipt";
import PriceCheckIcon from "@mui/icons-material/PriceCheck";
import PlayArrowIcon from "@mui/icons-material/PlayArrow";
import AppLayout from "../../components/AppLayout/AppLayout";
import httpRequest from "../../httpRequest";
import { useStyles } from "./styles";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || "http://localhost:5001";

const COLUMNS = [
  { field: "product_code", headerName: "Product Code", flex: 1, minWidth: 120 },
  { field: "po_qty", headerName: "PO Qty", flex: 0.7, minWidth: 90, type: "number" },
  { field: "grn_qty", headerName: "GRN Qty", flex: 0.7, minWidth: 90, type: "number" },
  { field: "invoice_qty", headerName: "Invoice Qty", flex: 0.7, minWidth: 100, type: "number" },
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
    headerName: "Invoice Price",
    flex: 0.8,
    minWidth: 110,
    type: "number",
    valueFormatter: (params) => params.value?.toFixed(2),
  },
  { field: "issue", headerName: "Issue", flex: 2, minWidth: 250 },
];

const SECTION_CONFIG = [
  {
    key: "missing",
    label: "Missing Items",
    color: "#f44336",
    bgColor: "rgba(244, 67, 54, 0.15)",
    Icon: RemoveCircleOutlineIcon,
    description: "Items in PO but not in GRN or Invoice",
  },
  {
    key: "extra",
    label: "Extra Items",
    color: "#ff9800",
    bgColor: "rgba(255, 152, 0, 0.15)",
    Icon: AddCircleOutlineIcon,
    description: "Items in GRN/Invoice but not in PO",
  },
  {
    key: "delivery_mismatch",
    label: "Delivery Mismatch",
    color: "#e91e63",
    bgColor: "rgba(233, 30, 99, 0.15)",
    Icon: LocalShippingIcon,
    description: "PO quantity ≠ GRN quantity",
  },
  {
    key: "invoice_mismatch",
    label: "Invoice Mismatch",
    color: "#9c27b0",
    bgColor: "rgba(156, 39, 176, 0.15)",
    Icon: ReceiptIcon,
    description: "GRN quantity ≠ Invoice quantity",
  },
  {
    key: "quantity_mismatch",
    label: "Quantity Mismatch",
    color: "#ff5722",
    bgColor: "rgba(255, 87, 34, 0.15)",
    Icon: WarningAmberIcon,
    description: "PO / GRN / Invoice quantities not equal",
  },
  {
    key: "price_mismatch",
    label: "Price Mismatch",
    color: "#2196f3",
    bgColor: "rgba(33, 150, 243, 0.15)",
    Icon: PriceCheckIcon,
    description: "PO price ≠ Invoice price",
  },
];

const MatchingPage = () => {
  const classes = useStyles();
  const [poList, setPoList] = useState([]);
  const [selectedPo, setSelectedPo] = useState("");
  const [loading, setLoading] = useState(false);
  const [loadingPoList, setLoadingPoList] = useState(true);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);

  // Fetch PO list on mount
  useEffect(() => {
    const fetchPoList = async () => {
      try {
        const res = await httpRequest.get(`${BACKEND_URL}/api/match/po-list`);
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
      const res = await httpRequest.get(`${BACKEND_URL}/api/match/${selectedPo}`);
      if (res.data.error) {
        setError(res.data.error);
      } else {
        setResult(res.data);
      }
    } catch (err) {
      const msg = err.response?.data?.error || err.message;
      setError(msg);
    } finally {
      setLoading(false);
    }
  }, [selectedPo]);

  const totalIssues = result
    ? SECTION_CONFIG.reduce((sum, s) => sum + (result[s.key]?.length || 0), 0)
    : 0;

  const selectedPoData = poList.find((p) => p.po_number === selectedPo);

  return (
    <AppLayout userName="Demo User">
      <div className={classes.content}>
        {/* Header */}
        <div className={classes.header}>
          <Typography className={classes.title}>
            <CompareArrowsIcon sx={{ fontSize: 32, verticalAlign: "middle", mr: 1, color: "#854de0" }} />
            Three-Way Match
          </Typography>
          <Typography className={classes.subtitle}>
            Compare Purchase Order → Goods Receipt → Invoice to detect mismatches
          </Typography>
        </div>

        {/* PO Selector */}
        <div className={classes.selectorRow}>
          <Autocomplete
            freeSolo
            id="po-selector"
            className={classes.selectField}
            options={poList.map((po) => po.po_number)}
            value={selectedPo}
            onInputChange={(event, newInputValue) => {
              setSelectedPo(newInputValue || "");
              setResult(null);
              setError(null);
            }}
            onChange={(event, newValue) => {
              setSelectedPo(newValue || "");
              setResult(null);
              setError(null);
            }}
            renderInput={(params) => (
              <TextField 
                {...params} 
                label="Purchase Order" 
                variant="outlined" 
                placeholder="Type or select PO number" 
                InputProps={{
                  ...params.InputProps,
                  endAdornment: (
                    <>
                      {loadingPoList ? <CircularProgress color="inherit" size={20} /> : null}
                      {params.InputProps.endAdornment}
                    </>
                  ),
                }}
              />
            )}
          />

          <Button
            id="run-match-btn"
            variant="contained"
            className={classes.matchButton}
            onClick={runMatch}
            disabled={!selectedPo || loading}
            startIcon={loading ? <CircularProgress size={20} color="inherit" /> : <PlayArrowIcon />}
          >
            {loading ? "Matching..." : "Run Match"}
          </Button>
        </div>

        {/* PO Info */}
        {selectedPoData && (
          <div className={classes.poInfo}>
            <div className={classes.poInfoItem}>
              <span className={classes.poInfoLabel}>PO Number</span>
              <span className={classes.poInfoValue}>{selectedPoData.po_number}</span>
            </div>
            <div className={classes.poInfoItem}>
              <span className={classes.poInfoLabel}>Date</span>
              <span className={classes.poInfoValue}>{selectedPoData.po_date}</span>
            </div>
            <div className={classes.poInfoItem}>
              <span className={classes.poInfoLabel}>Store</span>
              <span className={classes.poInfoValue}>{selectedPoData.store_code}</span>
            </div>
            <div className={classes.poInfoItem}>
              <span className={classes.poInfoLabel}>Supplier</span>
              <span className={classes.poInfoValue}>{selectedPoData.supplier_code}</span>
            </div>
          </div>
        )}

        {/* Error */}
        {error && (
          <div className={classes.errorBanner}>
            <ErrorOutlineIcon sx={{ color: "#c62828", fontSize: 32 }} />
            <Typography sx={{ color: "#c62828", fontWeight: 600, fontSize: "1.05rem" }}>
              {error}
            </Typography>
          </div>
        )}

        {/* Loading */}
        {loading && (
          <div className={classes.loader}>
            <CircularProgress size={48} sx={{ color: "#854de0" }} />
          </div>
        )}

        {/* Results */}
        {result && !loading && (
          <>
            {/* Summary Cards */}
            <div className={classes.summaryGrid}>
              {SECTION_CONFIG.map((section) => {
                const count = result[section.key]?.length || 0;
                return (
                  <div className={classes.summaryCard} key={section.key}>
                    <div className={classes.summaryIconRow}>
                      <div>
                        <div className={classes.summaryCount} style={{ color: count > 0 ? section.color : "#4caf50" }}>
                          {count}
                        </div>
                        <div className={classes.summaryLabel}>{section.label}</div>
                      </div>
                      <div
                        className={classes.summaryIcon}
                        style={{ backgroundColor: count > 0 ? section.bgColor : "rgba(76, 175, 80, 0.15)" }}
                      >
                        <section.Icon sx={{ color: count > 0 ? section.color : "#4caf50", fontSize: 24 }} />
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>

            {/* All matched banner */}
            {totalIssues === 0 && (
              <div className={classes.matchedBanner}>
                <CheckCircleIcon sx={{ color: "#2e7d32", fontSize: 40 }} />
                <Typography sx={{ color: "#2e7d32", fontWeight: 700, fontSize: "1.2rem" }}>
                  All items matched perfectly — No discrepancies found
                </Typography>
              </div>
            )}

            {/* Detail Tables */}
            {SECTION_CONFIG.map((section) => {
              const items = result[section.key];
              if (!items || items.length === 0) return null;
              return (
                <div key={section.key}>
                  <Typography className={classes.sectionTitle}>
                    <section.Icon sx={{ color: section.color }} />
                    {section.label}
                    <span
                      className={classes.badge}
                      style={{ backgroundColor: section.bgColor, color: section.color }}
                    >
                      {items.length}
                    </span>
                  </Typography>
                  <Paper className={classes.tableContainer} elevation={0}>
                    <DataGrid
                      rows={items.map((item, idx) => ({ id: idx, ...item }))}
                      columns={COLUMNS}
                      pageSize={5}
                      rowsPerPageOptions={[5, 10, 25]}
                      autoHeight
                      disableSelectionOnClick
                      sx={{
                        minHeight: 200,
                        "& .MuiDataGrid-virtualScroller": {
                          minHeight: 100,
                        },
                      }}
                    />
                  </Paper>
                </div>
              );
            })}
          </>
        )}

        {/* No data yet */}
        {!result && !loading && !error && (
          <div className={classes.noData}>
            <CompareArrowsIcon sx={{ fontSize: 64, color: "rgba(133, 77, 224, 0.4)", mb: 2, display: "block", mx: "auto" }} />
            <Typography sx={{ color: "#666", fontSize: "1.1rem" }}>
              Select a Purchase Order and click "Run Match" to begin validation
            </Typography>
          </div>
        )}
      </div>
    </AppLayout>
  );
};

export default MatchingPage;
