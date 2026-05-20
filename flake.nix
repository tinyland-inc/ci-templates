{
  description = "tinyland ci-templates validation shell";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs =
    { nixpkgs, flake-utils, ... }:
    flake-utils.lib.eachDefaultSystem (
      system:
      let
        pkgs = nixpkgs.legacyPackages.${system};
      in
      {
        devShells.default = pkgs.mkShell {
          buildInputs = with pkgs; [
            git
            gitleaks
            gh
            just
            jq
            ruby
            python3
            python3Packages.jsonschema
            shellcheck
          ];
          shellHook = ''
            echo "ci-templates dev shell"
            echo "  just   $(just --version)"
            echo "  jq     $(jq --version)"
            echo "  ruby   $(ruby --version | awk '{print $1, $2}')"
            echo "  python $(python3 --version)"
          '';
        };
      }
    );
}
