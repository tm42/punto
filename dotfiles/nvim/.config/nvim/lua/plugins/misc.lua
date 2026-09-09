-- ============================================================================
-- Miscellaneous Small Plugins
-- ============================================================================
-- Seven small plugins, each on its own defaults. Two are wired to something else
-- and will not make sense read alone:
--
-- nvim-autopairs registers a `confirm_done` handler on nvim-cmp, so accepting a
-- function completion does not leave you with a doubled bracket. That is the
-- only link between this file and completion.lua.
--
-- neoscroll claims <C-u> <C-d> <C-b> <C-f> at VeryLazy, which is AFTER
-- keymaps.lua loads. Anything mapping those keys there is silently overridden —
-- which is why the centring remaps that used to live in keymaps.lua are gone.
-- ============================================================================

return {
  -- Auto-close brackets, quotes, etc.
  {
    "windwp/nvim-autopairs",
    event = "InsertEnter",
    config = function()
      require("nvim-autopairs").setup({
        check_ts = true, -- Use treesitter for smarter pairing
      })
      -- Integrate with nvim-cmp
      local cmp_autopairs = require("nvim-autopairs.completion.cmp")
      local cmp = require("cmp")
      cmp.event:on("confirm_done", cmp_autopairs.on_confirm_done())
    end,
  },

  -- Surround text objects: ys/ds/cs in normal, S in visual
  {
    "kylechui/nvim-surround",
    version = "*",
    event = "VeryLazy",
    config = function()
      require("nvim-surround").setup()
    end,
  },

  -- File icons (used by neo-tree, lualine, telescope)
  {
    "nvim-tree/nvim-web-devicons",
    lazy = true,
  },

  -- Smooth scrolling (optional but nice)
  {
    "karb94/neoscroll.nvim",
    event = "VeryLazy",
    config = function()
      require("neoscroll").setup({
        mappings = { "<C-u>", "<C-d>", "<C-b>", "<C-f>" },
        hide_cursor = true,
        stop_eof = true,
        respect_scrolloff = false,
        cursor_scrolls_alone = true,
      })
    end,
  },

  -- Highlight other occurrences of word under cursor
  {
    "RRethy/vim-illuminate",
    event = { "BufReadPost", "BufNewFile" },
    config = function()
      require("illuminate").configure({
        delay = 200,
        filetypes_denylist = {
          "neo-tree",
          "Telescope",
        },
      })
    end,
  },

  -- Better UI for inputs and selects
  {
    "stevearc/dressing.nvim",
    event = "VeryLazy",
    config = function()
      require("dressing").setup({
        input = { enabled = true },
        select = { enabled = true },
      })
    end,
  },
}
