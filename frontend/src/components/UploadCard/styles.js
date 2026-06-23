import { makeStyles } from "@mui/styles";
import { COLORS } from "../../styles/constants";

export const useStyles = makeStyles({
  rootContainer: {
    position: "relative",
    margin: "40px auto",
    padding: "40px",
    width: "420px",
    borderRadius: "24px",
    backgroundColor: "rgba(255, 255, 255, 0.85)",
    backdropFilter: "blur(16px)",
    boxShadow: "0 10px 40px 0 rgba(31, 38, 135, 0.15)",
    border: "1px solid rgba(255, 255, 255, 0.4)",
    textAlign: "center",
    transition: "all 0.3s ease-in-out",
  },
  title: {
    fontWeight: "800 !important",
    color: "#2c3e50",
    marginBottom: "25px !important",
    letterSpacing: "-0.5px !important",
  },
  dropzone: {
    marginTop: "24px",
    border: `2px dashed ${COLORS.PRIMARY}`,
    borderRadius: "16px",
    padding: "30px 20px",
    cursor: "pointer",
    backgroundColor: "rgba(100, 57, 183, 0.03)",
    transition: "all 0.2s ease",
    "&:hover": {
      backgroundColor: "rgba(100, 57, 183, 0.08)",
      transform: "translateY(-2px)",
      boxShadow: "0 8px 16px rgba(100, 57, 183, 0.12)",
      borderColor: "#4a268e",
    },
  },
  fileInput: {
    display: "none",
  },
  icon: {
    fontSize: "54px !important",
    color: COLORS.PRIMARY,
    marginBottom: "12px",
  },
  fileName: {
    marginTop: "8px !important",
    fontWeight: "600 !important",
    color: "#34495e",
  },
  loader: {
    margin: "24px auto 0",
    display: "flex",
    justifyContent: "center",
  },
});
