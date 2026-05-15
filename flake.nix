{
  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixpkgs-unstable";
    pyproject-nix = {
      url = "github:pyproject-nix/pyproject.nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };

  outputs = inputs: let
    system = "x86_64-linux";
  in {
    devShells.${system} = let
      pkgs = import inputs.nixpkgs {
        config.allowUnfree = true;
        inherit system;
        overlays = [
          (self: super: rec {
            # https://github.com/NixOS/nixpkgs/blob/c339c066b893e5683830ba870b1ccd3bbea88ece/nixos/modules/programs/nix-ld.nix#L44
            # > We currently take all libraries from systemd and nix as the default.
            pythonldlibpath = inputs.nixpkgs.lib.makeLibraryPath (
              with super; [
                zlib
                zstd
                stdenv.cc.cc
                curl
                openssl
                attr
                libssh
                bzip2
                libxml2
                acl
                libsodium
                util-linux
                xz
                systemd
              ]
            );
            # here we are overriding python program to add LD_LIBRARY_PATH to it's env
            python = super.stdenv.mkDerivation {
              name = "python";
              buildInputs = [super.makeWrapper];
              src = super.python313;
              installPhase = ''
                mkdir -p $out/bin
                cp -r $src/* $out/
                wrapProgram $out/bin/python3 --set LD_LIBRARY_PATH ${pythonldlibpath}
                wrapProgram $out/bin/python3.13 --set LD_LIBRARY_PATH ${pythonldlibpath}
              '';
            };
          })
        ];
      };
    in {
      default = pkgs.mkShell {
        packages = with pkgs; [
          nodejs
          python
          uv
          bun
          jaq
          pre-commit
          just
          ruff
          unzip
          playwright-driver.browsers
        ];
        PLAYWRIGHT_BROWSERS_PATH = "${pkgs.playwright-driver.browsers}";
        PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD = "1";
        shellHook = ''
          VENV_DIR=".venv"
          if [ ! -d "$VENV_DIR" ]; then
            echo ">>> Virtual environment '$VENV_DIR' not found. Creating..."
            uv venv -p python
            echo ">>> Virtual environment created."
          fi

          source "$VENV_DIR/bin/activate"

        '';
      };
    };
  };
}
