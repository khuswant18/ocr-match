import React, { useState } from "react";
import { IconButton, Menu, MenuItem } from "@mui/material";
import AccountCircleIcon from "@mui/icons-material/AccountCircle";
import ProfileModal from "../ProfileModal/ProfileModal";
import { COLORS } from "../../styles/constants";

const ProfileIcon = () => {
  const [open, setOpen] = useState(null);
  const [showProfileOpen, setShowProfileOpen] = useState(false);

  const handleMenuOpen = (event) => {
    setOpen(event.currentTarget);
  };

  const handleMenuClose = () => {
    setOpen(null);
  };

  const handleProfileModalOpen = () => {
    setShowProfileOpen(true);
    setOpen(null);
  };

  const handleCloseProfileModal = () => {
    setShowProfileOpen(false);
  };

  return (
    <>
      <IconButton sx={{ p: 0.1, color: "white" }} onClick={handleMenuOpen}>
        <AccountCircleIcon
          fontSize="large"
          sx={{
            "&:hover": {
              color: COLORS.PRIMARY,
            },
          }}
        />
      </IconButton>
      <Menu anchorEl={open} open={Boolean(open)} onClose={handleMenuClose}>
        <MenuItem onClick={handleProfileModalOpen}>Profile</MenuItem>
      </Menu>
      <ProfileModal open={showProfileOpen} onClose={handleCloseProfileModal} />
    </>
  );
};

export default ProfileIcon;
