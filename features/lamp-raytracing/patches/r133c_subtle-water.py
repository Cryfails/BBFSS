#!/usr/bin/env python3
"""Apply or revert the approved r133c Stage A on exact b99 water sources.

Set R133C_ROOT or pass --root TREE, then run check, apply, or revert.
The five-file payload keeps the t133a logger and requires its exact helper SHA.
Start with BB_WATER_AMBIENT=indoor and BB_WATER_PHASE_RATE=0.20.
BB_WATER_MOTION still controls amplitude. Unset mode preserves legacy behavior.
Revert restores exact b99 bytes.
"""

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile
import zlib


PAYLOAD = (
    'c-qBV33J;xvi>WGww$37M&W%Zu~W8ZW_M~Q6IYzAyjQkM1rngdHASj;*zrs9-(NR)i<IR!$*ybcNFdSZ^XqN^b8#`@@iL70%jKqc'
    'nXM?>WX8*zknv>UCn<lqO0s-`<2=n?`n1UM(9dRmvffPO3FnMjo^R-?Zt14SOowvS(R>(VuIhNI=~%k21&&PvU(+-z@Jv^;nZb-e'
    'wS5~%D4I=uPtz?eV1cWtx~^&-r9O2$!*X?7F$3N6Jnm>zH*DsanrC?$^O)}NK(qXbd~u=MhK#=x0zZBdXE_OPxUZ27IV?X(%h@NH'
    'EN6G*ISJ!jdYj~75=*DY|2qHh$Laav?Yj?uy!&hM{@q7qI-S0{OfTa}k6fISG`Urf-oEK#_JcS<iq&FQ@`a%&vZ1K*q_?t{BoU!&'
    'FXX_&A(4WJE;I6!G;9C<=kebc$8S&m`0cL`Q}X1HC`C(BRb@lf8<O?U*P6xpCk%*GEixsax1ZwA%a`Ps+@^H1;f!QCU2lj_<2cC)'
    '3&AJiWf5j8LP^d)@rdNBFe9h$&i)skGJ<d2reV%!W0XNFI$=qiq>G!7-^$hJ+a!(HtFZ~lYz_*1U7F;}7xLsI&3Sqj!qQSM?;<wc'
    'AzGzu5Tf9t3w~|%soAojTa7*&J?_>YKDo_`H8}#y%*+uM!Zls;^BjUr%6uO4MYvwdWFw<u3@KfDGRbDN<5vR<raUjwxU%{c@cEdS'
    'UPSaRDe~D0WK%s=Q+?0%6osh}XolvijsYW#tA?kTw&FOJ6_`GTwdz}3u^orn%=AsipwtBt)buQ_Yo@I+MKigkxK#Jmz;s-yDn?)i'
    'rfUIED2}J8FvNY8+6L1MfDbDO6k5hLgtbui-xv=-pmDD!hT>WUdT1E4BuPOZLBxFwQF2Su4Y>{T74eHS1@pY{Xv|<3{H64b?7?b-'
    '>7X$Vo>fHGG;TGwp($NwLUS6o4AW$~VH$?3D4M7E)YG}Ga;62K1lO<>OHp*6>kd;5hpQH+%=KKwpbTISNO-!XFvoHL;apSk8Px+@'
    '_n7M#z6Nlsdx0BR%m!_`@RF+Vz%+H=^*r!Q-LVwZ9QdhLX)cWYs9>DD_E#y$dsO?frE0Q;*bv4Ms`e&<NIhmZH1@f4o`Zs(k__Xg'
    '@FGq!4iUoOdx=U}&gOHPru6Q05G531PCt4IdXAY)!~nbj>RRTjj>DHzD}oHsOppmPFfD+CRIM>3Z^{RL1SlglD=RZaCU5Dd^PF#{'
    'WRBl!psqxyNdGJ2?AKiCbKc>j43{6XxQIji{kd9{ci~n=c(bAzU!<@cXjPpl_iDY;Pc3niEi7;uOV_s&P;Uh>AO1Y+tk{|Fz<je!'
    'HQ7wObrD|Gwhq<_lRCrC$-6aQQt2bT;gOIOMyEiYfikq20-w&pUOxU#y0sVs>d3#L$d*xtO~<5_0{#%#@*V`1O2zmqnm)sPmv3vE'
    'f7+z=v|o8ZiwM=G%rxayH(@;4n%nWsYF6`l1NY^k07O7AE~03Yr>{mWUHO904tP-x`oZO7@)RbwxujYT2}0?BZ;+=?$uqIQA^GL<'
    'Quzf3`mutvrz0NO3mtr^iW}jO^PW&m+yHNdpOfRN!fBLIWKdI((<t$;YcWayLva8y?-o8jdsWlHIU?S$ILX^QE-1|BdAR0_O@eh?'
    'M6>+!*X9L5x_}3|w#Z2UNRE1IEmam^kWFrIJfKn55^r>UTSi8W3iWeHN$+`(a;S`gB#M&T3@Rhw5Ys%#({Q<jEW~d(<f#?>!Ds6*'
    'O(BKBe`St>ItsEfNdkiPOjAG!ocR#?*HWMVjPqC?5jsw82bj`zm659DiB!Kyj!?2-tbW>|n8uyAHPd_8mMx=YjVP*0`rv|<We$ai'
    'Bb@A`*055MeA9O-R)89yVt8FD<wydJkr%>QrqJ#bQ1y3lzov@MF%*;A-f-<k$ZPLGqc3p#zPjq9A>3E4*p<oWuX4v?!c=`!`1<P6'
    '1<cL$qV4E5*w9(7<_FX<;g8|ins55L6FAVSK?mkjLxG|NsukvIuFs$(Gy_j_7<3pmH=zjhIgo%VE^r-%bB$>(H(j5)+;eTy&^R{~'
    'j|R-6PT=__hi1`K;2&mtu4CJtqU)xkVfms065}r-v53DCd@GQUI@U*Rg?_hJs%pSPa&gsnk}hgPx@gdG$#WjxNSBk7lf}p555K*y'
    '>&nYXzviy6Qp~L}5lrI)*x{H=E+^&UFcBTK^^~vD0CCGV`&d}TV<o0YHM>OZqx{L~d|vjX^LZyv?GW$mAIImvE#AXtV06G(lhQj7'
    'jSDYmmhm)~#!GMzck9W=<M(Ie^=qP5OZ2H^;s5a@kh+W?*ZtFTQa$a|M`&7E$ax+md3H1<uMdf)7|yf-TukAbrpOvLXoEsY_{Jup'
    'F|Tn@d|BL88lHU1oVtJ;VgFgDS+5fGc=0BPM^L2rcMFz=L0*AE%@0ar7_w%mEoVL3uf@WPs*vs>^;pVAIGOG$BL_cQsl3D@k<5k6'
    'qgD7`E}zt@5$yFje$!KCRiaj0kKitbF=0HXVRWHu%2g+!@88cDmc%1#SJPh{RZI-hR~i5DCWZVONF^_F?YiaHseHe}FDC*`4lB&6'
    'mRyMJad=QP10@TK?C@abE}PK;80`#SPWCO<*6c9DX$eJ1yyUng05*lktfbfV&2L|eF2h_T)J5V!#NY7rkcAlqjkC+i9<?;87mAR{'
    'mMLV>9rRFg55cZ^%f_HP(rFSD(IiNs!|5%sZ-rhU@Au`A%^VT%rUrexy9Gs;6L7I*h7N%i!hZpV7>wb^TN+(MO8<AU2HWwB=P-B)'
    'h*&Cl^4+u!vJN%DBY={lZqcnR(}cTBiZ~0GF=vA^vMxNE2kppp4Bj$p$HzptZ>f6_=9`yASuK#&-IldkElrYqhRT`_TGU-H$`xp}'
    'U8im-vhLVT*NxD%Rql)w=aul-pw50Rxb!D{IHggPHF~+B5hRll^b@#Mq1NR@?3^|^OG;H;_owr^ifVLtFw+94YLm5SQVw7l0VZVu'
    'axl{ac@HLBPRf1;cQ**6k!6H!i6RPJ(trhNFrx9fT?8xBt&<yY-j3~{3oJkW6O0PwLQ<qY{|j(L>M3RmKpwWc+6z|QQDj3k$M)-+'
    '8g$E$t<fDrHlS9SZ0~DVJT`iNeONm0Xpthiv}!GI_&sxRSyzW;-SPeFlF*jJRE{wdt>%e`9d<UK3tV2r#oFWP3<@JwmTGIhPSU$Y'
    'l0ugO_z}@hoZSPQBh}M<UbU{!PywoMi!^F9v2_E1YAeRbzE#uqJ+#|fVAtHVd~K_b$Udu^v>JoZn@5g|_B+AWyIXZ&ZPYJc$axWe'
    'q;U=)GR3cdLOqss2P)`VbsErd`L{CE<J7TLiJ{wc>25jCKArW#$+BG8#{KABp>R}tGj6MR-X=*)yi&Y{fR+~k1v~@nLWBxJ9<g6C'
    'g4`3_@yEdx$iPz=#nhJ(kTPH4E)x{?%Cuv|J#qD)U<4K7II^v4B}<JdI-3n0ZtpR|*v!7-A;H;r&eDxdj@t%cwHHV4%JNMTJ4kf1'
    'i9)CZtHNw66}Mq3yi%^VvdgFP{@w%ABy?JwV~NK%`Dziublj9IQoiu1zk)S=SUII~-Ivu}+*ktsAwukDyYiGbqx<=vze3EEdT8FO'
    'K~-$^z~ldfg1$wLr*%0nZ(7(Me6+ah+PbVNnz}D)F^nXJsU9E;d&))qWm7N~@x_K_8Gfy%CvkK)?I*nl1?6|GgYrOLR+T#FaLE!('
    '3tg+H-~s$r$M`#*$-fJvfd}p5WcsQ{RUF<ArT)n*bRA=;;2~q6CRI@t(39y7>@F1g0K0YHD+xM4(6ZY((x%8(v--Njwyfpn>b?Wg'
    '6>h%U{JZ^Xc+CP(9P_KV>rt~^hitnaz0(07vd7YJTL$YajBmt!g$w%%FA7vK`!I1{ja)*gMfmci%gxW!Y0sD%Mv*<T4cG5I4ze;w'
    '`pM?5yaquIicipoLbVZ<*G4=})|7DoqJ*R&05=HLIo_AVamp%OgBF2!7)2z7u4}r#eb_EQKhktFpZ}RGKhPy6E{4Ig;^A_Yk2iNe'
    'UYc&F{R7zEOQ*qm=-eiN_3&q>J|`{a13qH#J9=Ls9v1EwV^^Z^looI540h1Qr<{K{etUMcg>R*t=Xmc(f*x^0bI5gBW0{IC#1O|F'
    'X_E3JVhg+rvbT}iaYyJ8()~aQ_uk#=0PIj!p&JuIQdLG;zY+Yyi0+|ZC(^|dZPOvXcGAfx7&Y^dt3|SXddHHOOJheZ!{hIreJW(f'
    'XQj49t0#^ce5ib1<AWnfv@bl(W@~YQ4bK?5x<A3KjORq4V-_X2``0rKbhO!Ee;Hp~w0N6tE}HpQquVafI?sd#HlN7z!yUeX$0m!j'
    '|G9c~&-`mB{q|7!=Wk~phBTf(?@&oO-IA*3TK9<uI<8DP(8{=p2e5^=0Z)*9NeChLYhszG#h@UcJ`g|Zpe%*_iMTVgPB%`#K0W_`'
    'LsaaZ$2Wde)ih;Q)4MxD7*5rtJYecs`AM!7Uw!Z+PE)y+RmPqadr>|}MoAz>hIwZj5Ffd48JBWT>PNF9bm9V@YxY*2@z=~Nf*CsF'
    'DMA+%I+@gAStd8vU@>vK5$v|)SlXO~xNXHxll7($*HW5;8l*FoA9ODERJ=PdeZ^4i9g-xnaD^~`Pm^LpUJ!LkUbX`=k;)u>|6BXG'
    'Qb#Kjkq^2?*pbrydy2eAng3mdc9c4L|5w!%8(h*chP7Y`>}`2{xTCx#Uq<i+AD=>K>?$<d4p1z!cLk{_?Z!{*=h)7T>V7CjXT|-j'
    '3mvH{>d5^GI>Jx8bo40BTY|{Bu2{0F*VesfHv^iV9^ki`K{QW08_d01!aM7mZ#lA_jh$GZc<(vxRL<vTk2w0lJ4l>wVxDF2-GuMu'
    '4X1-*-?<Mw26nMyJeXMl!E@yDQzmy0kE$c+>Qt$GA?KU&Q%czbmf3Z_gy)@t(f&zOeJtG^IaOO_f}#DZNpbR`dcT;Kd60D60NOsO'
    'J-~k<U>G=nlFOt1b@njD@hDt|;_~e$au7u@MO1#(H!xJ0L2IH9=pLIxvwmgO9EA3&u$i#=w5`qh$MKb$?OAYeQs1xisw=z7)%|3C'
    '`T>5QDbX%8N)bEg!q!u{iu*Vz2ks}@DYjeJkcYLROt#DN{dAlDraEI55hVT`NxfEM`on0U^K}kNzY-ontbRXC3g}fWyz%Eg9D29Z'
    'Is&{~jq&3sHcWo!{Yw0wLu^-bP2KhwHEmsYsp}ZFt$MCQRV~m0YA}WSlv0aPL$OTNGy=_bEX^=ESD0zyZAjnJ6wS5`-LrN0pnA5V'
    '1&XdvKj13oo&s-LZV<S-rrBQLc^Z@}s_nwdfu;rGb|n@uN_*n~`d{y~;&X5!TSrF!zI69eUVnOdJ#W}Oes1rnUj09Z$s6z'
)

LOGGER = Path("engine/gpu/shadps4/video_core/renderer_vulkan/water_evidence.h")
LOGGER_SHA = "e16960a399ec2e5f15af1530df03dcb099030aa6e1df01bbda739c8bfb4d78d9"


def digest(data):
    return hashlib.sha256(data).hexdigest()


def read(path):
    if any(part.is_symlink() or getattr(part, 'is_junction', lambda: False)() for part in (path, *path.parents)):
        raise ValueError(f"linked path {path.name}")
    return path.read_bytes()


def transform(data, changes, revert):
    lines = data.decode().splitlines(keepends=True)
    for old_at, new_at, old_text, new_text in reversed(changes):
        index, old, new = (new_at, new_text, old_text) if revert else (old_at, old_text, new_text)
        expected = old.splitlines(keepends=True)
        stop = index + len(expected)
        if lines[index:stop] != expected:
            raise ValueError("source hunk mismatch")
        lines[index:stop] = new.splitlines(keepends=True)
    return "".join(lines).encode()


def write_exact(path, previous, data):
    if read(path) != previous:
        raise ValueError(f"{path.name} changed during r133c")
    permissions = stat.S_IMODE(path.stat().st_mode)
    fd, name = tempfile.mkstemp(prefix=".r133c-", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
        temporary.chmod(permissions)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def run(root, mode):
    if digest(read(root / LOGGER)) != LOGGER_SHA:
        raise ValueError("t133a water evidence helper differs from b99")
    entries = json.loads(zlib.decompress(base64.b85decode(PAYLOAD)))
    sources = [(root / path, before, after, changes, read(root / path))
               for path, before, after, changes in entries]
    states = set()
    for path, before, after, _, data in sources:
        source_sha = digest(data)
        if source_sha == before:
            states.add("base")
        elif source_sha == after:
            states.add("applied")
        else:
            raise ValueError(f"{path.name} differs from its exact b99 or r133c SHA")
    if len(states) != 1:
        raise ValueError("partial r133c state")
    applied = states == {"applied"}
    count = len(sources)
    if mode == "check":
        print(f"r133c: {'applied' if applied else 'would apply'} ({count} files)")
        return
    if (mode == "apply") == applied:
        print(f"r133c: {'applied' if applied else 'already reverted'} ({count} files)")
        return

    updates = []
    for path, before, after, changes, data in sources:
        result = transform(data, changes, applied)
        if digest(result) != (before if applied else after):
            raise ValueError(f"{path.name} transformed SHA mismatch")
        updates.append((path, data, result))
    if applied:
        updates.reverse()
    completed = []
    try:
        for path, previous, result in updates:
            write_exact(path, previous, result)
            completed.append((path, previous, result))
    except (OSError, ValueError):
        for path, previous, result in reversed(completed):
            write_exact(path, result, previous)
        raise
    print(f"r133c: {'reverted' if applied else 'applied'} ({count} files)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("check", "apply", "revert"))
    parser.add_argument("--root", type=Path, default=os.environ.get("R133C_ROOT"))
    args = parser.parse_args()
    if args.root is None:
        parser.exit(1, "r133c refused: set R133C_ROOT or pass --root TREE\n")
    try:
        run(args.root.resolve(), args.mode)
    except (OSError, ValueError) as error:
        parser.exit(1, f"r133c refused: {error}\n")
