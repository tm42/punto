-- ============================================================================
-- Lualine: Status Line
-- ============================================================================
-- Stock lualine sections. Two deliberate settings and nothing else:
--   theme = "catppuccin-nvim"  follows the colorscheme rather than guessing, and
--                          follows its flavour too, so mocha is set in one place.
--                          Not "catppuccin": catppuccin ships catppuccin-nvim and
--                          one file per flavour, lualine ships no catppuccin at all,
--                          so that name matched nothing and lualine fell back to
--                          `auto` — visible only as a startup line pointing at
--                          :LualineNotices.
--   globalstatus = true    one bar for the whole window, not one per split —
--                          splits are already busy next to tmux's own bar
-- ============================================================================

return {
  "nvim-lualine/lualine.nvim",
  dependencies = { "nvim-tree/nvim-web-devicons" },
  event = "VeryLazy",
  config = function()
    require("lualine").setup({
      options = {
        theme = "catppuccin-nvim", -- Match our colorscheme and its flavour
        component_separators = { left = "", right = "" },
        section_separators = { left = "", right = "" },
        globalstatus = true, -- Single statusline for all windows
      },

      sections = {
        -- Left side
        lualine_a = { "mode" },
        lualine_b = { "branch", "diff", "diagnostics" },
        lualine_c = { { "filename", path = 1 } }, -- Show relative path

        -- Right side
        lualine_x = { "encoding", "fileformat", "filetype" },
        lualine_y = { "progress" },
        lualine_z = { "location" },
      },

      -- Inactive windows (when you have splits)
      inactive_sections = {
        lualine_a = {},
        lualine_b = {},
        lualine_c = { "filename" },
        lualine_x = { "location" },
        lualine_y = {},
        lualine_z = {},
      },
    })
  end,
}
