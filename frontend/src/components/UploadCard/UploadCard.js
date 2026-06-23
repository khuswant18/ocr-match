import { useContext, useState, useRef } from "react";
import { Typography, TextField, InputAdornment, Box } from "@mui/material";
import CloudUploadIcon from "@mui/icons-material/CloudUpload";
import ReceiptLongIcon from "@mui/icons-material/ReceiptLong";
import CheckCircleIcon from "@mui/icons-material/CheckCircle";
import { BarLoader } from "react-spinners";
import ButtonContained from "../StyledComponents/ButtonContained";
import OCRContext from "../../context/ocr-context";
import { useStyles } from "./styles";
import { COLORS } from "../../styles/constants";
const cv = window.cv;

const UploadCard = () => {
  const classes = useStyles();
  const ocrCtx = useContext(OCRContext);
  const [isLoading, setIsLoading] = useState(false);
  const fileInputRef = useRef(null);

  const PDFJS = require("pdfjs-dist/webpack");

  const readFileData = (file) => {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = (e) => {
        resolve(e.target.result);
      };
      reader.onerror = (err) => {
        reject(err);
      };
      reader.readAsDataURL(file);
    });
  };

  const convertPdfToImages = async (file) => {
    let image;
    const data = await readFileData(file);
    const pdf = await PDFJS.getDocument(data).promise;
    const canvas = document.createElement("canvas");
    const page = await pdf.getPage(1);
    const viewport = page.getViewport({ scale: 4.8 });
    const context = canvas.getContext("2d");
    canvas.height = viewport.height;
    canvas.width = viewport.width;
    canvas.style.width = "100%";
    await page.render({ canvasContext: context, viewport: viewport }).promise;
    image = canvas.toDataURL("image/png", 1.0);
    canvas.remove();
    return image;
  };

  const loadImage = () => {
    const img = new Image();
    img.onload = () => {
      const mat = cv.imread(img);
      cv.imshow("output", mat);
      mat.delete();
    };
    return img;
  };

  const saveImage = (file) => {
    ocrCtx.setOriginalImage(file);
    ocrCtx.setActualImage(file);
  };

  const handleImageUpload = async (event) => {
    setIsLoading(true);
    const file = event.target.files[0];
    ocrCtx.setFile(file);
    if (file.type === "application/pdf") {
      const image = convertPdfToImages(file);
      image.then(async (image) => {
        const img = loadImage();
        img.src = image;
        const base64Response = await fetch(`${image}`);
        const blob = await base64Response.blob();
        let fileImage = new File([blob], file.name, {
          type: "image/jpeg",
          lastModified: new Date().getTime(),
        });
        saveImage(fileImage);
        setIsLoading(false);
      });
    } else {
      const img = loadImage();
      img.src = URL.createObjectURL(file);
      saveImage(file);
      setIsLoading(false);
    }
  };

  const handleBoxClick = () => {
    if (!isLoading && fileInputRef.current) {
      fileInputRef.current.click();
    }
  };

  return (
    <div className={classes.rootContainer}>
      <Typography variant="h5" className={classes.title}>
        Upload Document
      </Typography>
      
      <TextField
        fullWidth
        label="PO Number"
        variant="outlined"
        value={ocrCtx.poNumber}
        onChange={(e) => ocrCtx.setPoNumber(e.target.value)}
        placeholder="e.g. 4017248"
        InputProps={{
          startAdornment: (
            <InputAdornment position="start">
              <ReceiptLongIcon sx={{ color: COLORS.PRIMARY }} />
            </InputAdornment>
          ),
          sx: { borderRadius: "12px", backgroundColor: "white" }
        }}
      />

      <div className={classes.dropzone} onClick={handleBoxClick}>
        <input
          type="file"
          ref={fileInputRef}
          onChange={handleImageUpload}
          className={classes.fileInput}
          accept="image/*,application/pdf"
        />
        {ocrCtx.file ? (
           <CheckCircleIcon className={classes.icon} sx={{ color: "#4caf50 !important" }} />
        ) : (
           <CloudUploadIcon className={classes.icon} />
        )}
        <Typography variant="body1" className={classes.fileName}>
          {ocrCtx.file ? ocrCtx.file.name : "Click to select a file"}
        </Typography>
        {!ocrCtx.file && (
          <Typography variant="body2" color="textSecondary" sx={{ mt: 1 }}>
            Supports JPG, PNG, PDF
          </Typography>
        )}
      </div>

      {isLoading && (
        <div className={classes.loader}>
          <BarLoader color={COLORS.PRIMARY} width={150} />
        </div>
      )}

      <Box mt={4}>
        <ButtonContained
          style={{ 
            width: "100%", 
            padding: "14px", 
            borderRadius: "12px", 
            fontSize: "16px", 
            fontWeight: "bold",
            letterSpacing: "1px"
          }}
          onClick={() => ocrCtx.setActivePage(1)}
          disabled={!ocrCtx.file || isLoading}
        >
          NEXT STEP
        </ButtonContained>
      </Box>
    </div>
  );
};

export default UploadCard;
