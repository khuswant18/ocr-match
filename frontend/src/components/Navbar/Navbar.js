import { useLocation } from "react-router-dom";
import MenuIcon from "@mui/icons-material/Menu";
import { IconButton, Typography } from "@mui/material";
import { useStyles } from "./styles";
import ProfileIcon from "../ProfileIcon/ProfileIcon";
import { COLORS } from "../../styles/constants";

const Navbar = (props) => {
  const classes = useStyles();
  const location = useLocation();

  const getPageTitle = () => {
    switch (location.pathname) {
      case "/":
        return `Welcome Back ${props.userName}!`;
      case "/history":
        return "Your scans";
      case "/users":
        return "Manage users";
      default:
        return "";
    }
  };

  return (
    <div className={classes.rootContainer}>
      <div className={classes.headingContainer}>
        {!props.sideMenuVisible && (
          <IconButton onClick={props.toggleSideMenu}>
            <MenuIcon
              sx={{
                color: "white",
                "&:hover": {
                  color: COLORS.PRIMARY,
                },
                marginTop: "-4px",
              }}
            />
          </IconButton>
        )}
        <Typography
          variant="h5"
          sx={{
            ml: 4,
            fontSize: { xs: "20px", sm: "24px", md: "26px" },
          }}
        >
          {getPageTitle()}
        </Typography>
      </div>
      <div className={classes.rightButtons}>
        <ProfileIcon />
      </div>
    </div>
  );
};

export default Navbar;
