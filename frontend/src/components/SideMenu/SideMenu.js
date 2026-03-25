import { useContext } from "react";
import { Divider } from "@mui/material";

import DashboardIcon from "@mui/icons-material/Dashboard";
import HistoryIcon from "@mui/icons-material/History";
import GroupIcon from "@mui/icons-material/Group";
import CompareArrowsIcon from "@mui/icons-material/CompareArrows";
import IconButton from "@mui/material/IconButton";
import ArrowBackIosIcon from "@mui/icons-material/ArrowBackIos";
import { useMediaQuery } from "@mui/material";

import userContext from "../../context/user-context";
import { useStyles } from "./styles";
import ProfileIcon from "../ProfileIcon/ProfileIcon";
import LinkItem from "./LinkItem/LinkItem";
import OCR_LOGO from "../../images/OCR-logo.png";
import { Link } from 'react-router-dom';
import { COLORS } from "../../styles/constants";

const SideMenu = (props) => {
  const userCtx = useContext(userContext);
  const { role } = userCtx;
  const classes = useStyles();
  const isSmallScreen = useMediaQuery("(max-width:540px)");
  const isExtraSmallScreen = useMediaQuery("(max-width:470px)");

  return (
    <div
      className={`${classes.rootContainer} ${
        props.visible ? "" : classes.rootContainerCollapsed
      }`}
      style={{
        display: "flex",
        flexDirection: "column",
        justifyContent: "space-between",
      }}
    >
      {props.visible && (
        <>
          <div>
            <div className={classes.closeContainer}>
              <IconButton onClick={props.onClose} className={classes.closeButton}>
                <ArrowBackIosIcon
                  sx={{
                    color: "white",
                    "&:hover": {
                      color: COLORS.PRIMARY,
                    },
                  }}
                />
              </IconButton>
            </div>
            <Link to="/">
              <img
                src={OCR_LOGO}
                alt="logo"
                className={classes.logo}
                width={isSmallScreen ? "40px" : "60px"}
                style={{
                  marginTop: isExtraSmallScreen ? "5px" : "-16px",
                  marginBottom: "24px",
                }}
              />
            </Link>
            <Divider />
            <div className={classes.linkContainer}>
              <LinkItem to="/" Icon={DashboardIcon} text="Dashboard" />
              <LinkItem to="/history" Icon={HistoryIcon} text="Your scans" />
              <LinkItem to="/matching" Icon={CompareArrowsIcon} text="Three-Way Match" />
              {role === "admin" && (
                <LinkItem to="/users" Icon={GroupIcon} text="Manage users" />
              )}
            </div>
          </div>
          <div className={classes.footerContainer}>
            <div>
              <ProfileIcon />
            </div>
          </div>
        </>
      )}
    </div>
  );
};

export default SideMenu;
