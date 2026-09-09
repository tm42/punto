-- ============================================================================
-- Keymaps
-- ============================================================================
-- Custom keybindings for Neovim.
-- Leader key is <Space> (set in init.lua)
--
-- Notation:
--   <leader>  = Space
--   <C-x>     = Ctrl + x
--   <S-x>     = Shift + x
--   <A-x>     = Alt + x
-- ============================================================================

local keymap = vim.keymap.set

-- Better escape - press jk quickly to exit insert mode
keymap("i", "jk", "<Esc>", { desc = "Exit insert mode" })

-- Clear search highlighting with Escape
keymap("n", "<Esc>", "<cmd>nohlsearch<CR>", { desc = "Clear search highlight" })

-- Save file with Ctrl+s (common muscle memory)
keymap({ "n", "i", "v" }, "<C-s>", "<cmd>w<CR><Esc>", { desc = "Save file" })

-- Quit with leader+q
keymap("n", "<leader>q", "<cmd>q<CR>", { desc = "Quit" })
keymap("n", "<leader>Q", "<cmd>qa!<CR>", { desc = "Quit all (force)" })

-- ============================================================================
-- Window Navigation (splits)
-- ============================================================================
-- Move between windows with Ctrl + hjkl
keymap("n", "<C-h>", "<C-w>h", { desc = "Move to left window" })
keymap("n", "<C-j>", "<C-w>j", { desc = "Move to lower window" })
keymap("n", "<C-k>", "<C-w>k", { desc = "Move to upper window" })
keymap("n", "<C-l>", "<C-w>l", { desc = "Move to right window" })

-- Resize windows with Ctrl+Arrow keys
keymap("n", "<C-Up>", "<cmd>resize +2<CR>", { desc = "Increase window height" })
keymap("n", "<C-Down>", "<cmd>resize -2<CR>", { desc = "Decrease window height" })
keymap("n", "<C-Left>", "<cmd>vertical resize -2<CR>", { desc = "Decrease window width" })
keymap("n", "<C-Right>", "<cmd>vertical resize +2<CR>", { desc = "Increase window width" })

-- Split windows
keymap("n", "<leader>sv", "<cmd>vsplit<CR>", { desc = "Split vertical" })
keymap("n", "<leader>sh", "<cmd>split<CR>", { desc = "Split horizontal" })
keymap("n", "<leader>sx", "<cmd>close<CR>", { desc = "Close split" })

-- ============================================================================
-- New Files & Buffers
-- ============================================================================
-- ns/nS prefill the cmdline with the current file's directory and stop there —
-- no trailing <CR>. Type a name and Enter to create it, or press Tab to pick an
-- existing one from the popup (wildoptions=pum is the default, so it is a menu).
--
-- %:p:h and not %:h: with :p the path is made absolute first, so a buffer with
-- no file behind it (neo-tree, an unnamed :enew) falls back to the cwd instead
-- of expanding to "" or a bare ".". fnameescape covers directories with spaces.
keymap("n", "<leader>ns", ":vsplit <C-r>=fnameescape(expand('%:p:h'))<CR>/",
  { desc = "New file in vsplit (file's dir)" })
keymap("n", "<leader>nS", ":split <C-r>=fnameescape(expand('%:p:h'))<CR>/",
  { desc = "New file in hsplit (file's dir)" })

-- Scratch buffers: no name, no path step. Naming happens at :w time.
keymap("n", "<leader>nb", "<cmd>vnew<CR>", { desc = "New buffer in vsplit" })
keymap("n", "<leader>nB", "<cmd>new<CR>", { desc = "New buffer in hsplit" })

-- A tab is a third destination and there are only two cases to spend, so here the
-- case means file-or-scratch rather than vertical-or-horizontal: nt takes the path
-- prefill that ns does, nT is the bare scratch buffer that nb is.
-- Move between tabs with gt/gT, and <C-w>T pulls the current split out into its
-- own tab. Both are built in; neither needs a mapping.
keymap("n", "<leader>nt", ":tabedit <C-r>=fnameescape(expand('%:p:h'))<CR>/",
  { desc = "New file in new tab (file's dir)" })
keymap("n", "<leader>nT", "<cmd>tabnew<CR>", { desc = "New buffer in new tab" })

-- ============================================================================
-- Buffer Navigation
-- ============================================================================
keymap("n", "<S-l>", "<cmd>bnext<CR>", { desc = "Next buffer" })
keymap("n", "<S-h>", "<cmd>bprevious<CR>", { desc = "Previous buffer" })
keymap("n", "<leader>bd", "<cmd>bdelete<CR>", { desc = "Delete buffer" })

-- ============================================================================
-- Text Manipulation
-- ============================================================================
-- Move lines up/down in visual mode
keymap("v", "J", ":m '>+1<CR>gv=gv", { desc = "Move selection down" })
keymap("v", "K", ":m '<-2<CR>gv=gv", { desc = "Move selection up" })

-- Stay in visual mode when indenting
keymap("v", "<", "<gv", { desc = "Indent left" })
keymap("v", ">", ">gv", { desc = "Indent right" })

-- No <C-d>zz / <C-u>zz here: neoscroll (misc.lua) maps both keys itself at
-- VeryLazy, which is after this file loads, so its smooth scroll wins and the zz
-- never runs. It recentres on its own.

-- Keep cursor centered when searching
keymap("n", "n", "nzzzv", { desc = "Next search result (centered)" })
keymap("n", "N", "Nzzzv", { desc = "Previous search result (centered)" })

-- Don't yank on paste in visual mode (keep original clipboard)
keymap("v", "p", '"_dP', { desc = "Paste without yanking" })

-- ============================================================================
-- Quick Access
-- ============================================================================
keymap("n", "<leader>e", "<cmd>Neotree toggle<CR>", { desc = "Toggle file explorer" })
keymap("n", "<leader>w", "<cmd>w<CR>", { desc = "Save file" })

-- Open personal cheatsheet in a horizontal split
keymap("n", "<leader>?", "<cmd>split ~/.nvimcheatsheet.md<CR>", { desc = "Cheatsheet" })

-- Format file via LSP
keymap("n", "<leader>cf", function() vim.lsp.buf.format() end, { desc = "Format file" })

-- Toggle soft wrap: word-safe (linebreak breaks at whitespace, never mid-word)
-- and non-destructive (display only, no line breaks written to the buffer).
-- Wrap point follows the window width, not a configurable column.
keymap("n", "<leader>gq", function()
  vim.wo.wrap = not vim.wo.wrap
  vim.wo.linebreak = vim.wo.wrap
end, { desc = "Toggle soft wrap (word-safe)" })

-- Commenting extras
-- gc and gcc are Neovim's own since 0.10 and need nothing here. These three came
-- from Comment.nvim, which was removed: it overrode the native pair with its own
-- mappings and asked treesitter for the commentstring first, and since Neovim 0.11
-- vim.treesitter.get_parser returns nil instead of throwing when no parser exists.
-- Its pcall only caught the throw, so gcc crashed in every filetype with no parser
-- installed — zsh and typescript among them.
--
-- gb/gbc are deliberately not rebuilt. 'commentstring' holds the line form only, so
-- block commenting needs a second source of truth this configuration does not have.
-- Resolved at the cursor, not off the buffer option, so that a comment written
-- inside a fenced code block gets that language's marker rather than markdown's.
-- This mirrors $VIMRUNTIME/lua/vim/_comment.lua's get_commentstring, which is a
-- local function in a private module and so cannot be called: capture metadata
-- first, then the deepest injected language containing the cursor, then the
-- buffer option. Being a copy, it can drift when Neovim changes its own.
--
-- get_parser returning nil is the ordinary case in a filetype with no parser and
-- must fall through rather than error. Not doing that is precisely what broke
-- Comment.nvim.
local function commentstring_at_cursor()
  local buf_cs = vim.bo.commentstring
  local ok, parser = pcall(vim.treesitter.get_parser, 0, "")
  if not ok or not parser then
    return buf_cs
  end

  local pos = vim.api.nvim_win_get_cursor(0)
  local row, col = pos[1] - 1, pos[2]

  -- Backwards, to prefer the narrower capture.
  local caps = vim.treesitter.get_captures_at_pos(0, row, col)
  for i = #caps, 1, -1 do
    local id, metadata = caps[i].id, caps[i].metadata
    local md_cs = metadata["bo.commentstring"]
      or (metadata[id] and metadata[id]["bo.commentstring"])
    if md_cs then
      return md_cs
    end
  end

  local range = { row, col, row, col + 1 }
  local found, level = nil, 0
  local function traverse(tree, depth)
    if not tree:contains(range) then
      return
    end
    for _, ft in ipairs(vim.treesitter.language.get_filetypes(tree:lang())) do
      local cs = vim.filetype.get_option(ft, "commentstring")
      if cs ~= "" and depth > level then
        found, level = cs, depth
      end
    end
    for _, child in pairs(tree:children()) do
      traverse(child, depth + 1)
    end
  end
  pcall(traverse, parser, 1)

  return found or buf_cs
end

local function comment_halves()
  local left, right = commentstring_at_cursor():match("^(.*)%%s(.*)$")
  if not left then
    return nil
  end
  return vim.trim(left), vim.trim(right)
end

-- Where the commentstring has a right half — html's `<!-- %s -->` is the one in
-- daily use — the cursor belongs between the two, not at end of line.
local function enter_comment(head, right, row)
  if right == "" then
    vim.api.nvim_win_set_cursor(0, { row, 0 })
    vim.cmd("startinsert!")
  else
    vim.api.nvim_win_set_cursor(0, { row, #head })
    vim.cmd("startinsert")
  end
end

keymap("n", "gcA", function()
  local left, right = comment_halves()
  if not left or left == "" then
    return
  end
  local line = vim.api.nvim_get_current_line()
  local head = line .. (line == "" and "" or " ") .. left .. " "
  vim.api.nvim_set_current_line(head .. (right == "" and "" or " " .. right))
  enter_comment(head, right, vim.fn.line("."))
end, { desc = "Comment at end of line" })

local function open_commented(below)
  local left, right = comment_halves()
  if not left or left == "" then
    return
  end
  local row = vim.fn.line(".")
  local head = vim.api.nvim_get_current_line():match("^%s*") .. left .. " "
  local at = below and row or row - 1
  vim.api.nvim_buf_set_lines(0, at, at, false, { head .. (right == "" and "" or " " .. right) })
  enter_comment(head, right, at + 1)
end

keymap("n", "gco", function()
  open_commented(true)
end, { desc = "Comment line below" })

keymap("n", "gcO", function()
  open_commented(false)
end, { desc = "Comment line above" })

-- Note: More keymaps are defined in plugin configs (telescope, lsp, etc.)
-- Press <Space> and wait to see all available mappings via which-key
