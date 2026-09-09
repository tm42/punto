-- ============================================================================
-- Treesitter: Parser Installation & Highlighting
-- ============================================================================
-- Ten parsers, installed on first launch if missing. Highlighting is Neovim's
-- own (vim.treesitter.start on FileType), not nvim-treesitter's module — the
-- pinned main branch no longer ships one.
--
-- That branch also shells out to the tree-sitter CLI and a C compiler, which is
-- what the guard in the config below is about.
-- ============================================================================

return {
  "nvim-treesitter/nvim-treesitter",
  build = ":TSUpdate",
  event = { "BufReadPost", "BufNewFile" },
  config = function()
    -- List of parsers to install
    local parsers = {
      "python", "lua", "vim", "vimdoc", "bash",
      "json", "yaml", "toml", "markdown", "markdown_inline",
    }

    -- nvim resolves ft=zsh to a lang=zsh grammar this list does not install, so a
    -- .zshrc would get no treesitter highlighting at all. nvim-treesitter does ship
    -- one — tier 1, maintained — and it was declined rather than missed: under the
    -- bash grammar a .zshrc parses into a single top-level ERROR node, and 830 of
    -- the captures still land inside it, so what the zsh grammar would buy is a
    -- usable tree, and nothing here reads the tree except the highlighter.
    -- The cost of bash is that zsh-only syntax — ${(f)...} parameter flags,
    -- anonymous functions, =~ globs — parses under a bash grammar and may highlight
    -- oddly rather than not at all. That is the trade, not an oversight.
    vim.treesitter.language.register("bash", "zsh")

    -- Install missing parsers on startup, in ONE :TSInstall rather than ten.
    vim.schedule(function()
      local missing = {}
      for _, parser in ipairs(parsers) do
        if not pcall(vim.treesitter.language.inspect, parser) then
          table.insert(missing, parser)
        end
      end
      if #missing == 0 then
        return
      end
      -- The pinned main branch shells out to the tree-sitter CLI and a C
      -- compiler, neither of which INSTALL.md installs. Without them every
      -- install fails, and the next launch retries and fails identically —
      -- forever, with no message. Say it once instead.
      if vim.fn.executable("tree-sitter") == 0 or vim.fn.executable("cc") == 0 then
        vim.notify(
          ("treesitter: %d parsers missing, and tree-sitter or cc is not on PATH. "
            .. "Install both, then :TSInstall %s"):format(#missing, table.concat(missing, " ")),
          vim.log.levels.WARN
        )
        return
      end
      vim.cmd("TSInstall " .. table.concat(missing, " "))
    end)

    -- Auto-enable treesitter highlighting for supported filetypes
    vim.api.nvim_create_autocmd("FileType", {
      callback = function()
        pcall(vim.treesitter.start)
      end,
    })
  end,
}
