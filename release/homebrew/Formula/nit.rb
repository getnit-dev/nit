class Nit < Formula
  include Language::Python::Virtualenv

  desc "AI testing, documentation & quality agent"
  homepage "https://getnit.dev"
  url "https://files.pythonhosted.org/packages/source/g/getnit/getnit-0.1.0.tar.gz"
  sha256 "PLACEHOLDER_SHA256"
  license "MIT"

  depends_on "python@3.12"

  def install
    virtualenv_install_with_resources
  end

  test do
    assert_match version.to_s, shell_output("#{bin}/nit --version")
  end
end
