import { useContext, useEffect, useState } from "react";
import OCRContext from "../../context/ocr-context";
import AppLayout from "../../components/AppLayout/AppLayout";
import Tabbar from "../../components/Tabbar/Tabbar";
import UploadCard from "../../components/UploadCard/UploadCard";
import PreprocessingCard from "../../components/PreprocessingCard/PreprocessingCard";
import OCRCard from "../../components/OCRCard/OCRCard";
import SummaryCard from "../../components/SummaryCard/SummaryCard";
import { useStyles } from "./styles";

const HomePage = () => {
  const classes = useStyles();
  const ocrCtx = useContext(OCRContext);
  const [activePage, setActivePage] = useState(0);

  useEffect(() => { 
    setActivePage(ocrCtx.activePage);
  }, [ocrCtx]); 

  return (
    <>
      <AppLayout>
        <Tabbar />
        <div className={classes.content}>
          {activePage === 0 && <UploadCard />}
          {activePage === 1 && <PreprocessingCard />}
          {activePage === 2 && <OCRCard />}
          {activePage === 3 && <SummaryCard />}
          <canvas className={classes.invoice} id="output" />
        </div>  
      </AppLayout>  
    </> 
  );
};

export default HomePage;
