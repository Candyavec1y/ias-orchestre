# -*- coding: utf-8 -*-
"""
Optimisation taboue avec horizon de planification compact — bloc opératoire / lits / places ambulatoires

Principales améliorations par rapport à la version d'origine :
  * Niveau 2 : évaluation INCRÉMENTALE (on ne recalcule que ce que le mouvement
    modifie) -> environ 50 à 100 fois plus de voisins évalués par seconde.
  * Niveau 2 : voisinage COMPLET (tous les déplacements) + échange d'un
    échantillon aléatoire de paires (l'ancien voisinage était tronqué et ne
    regardait que les premiers patients).
  * Niveau 2 : meilleure solution de départ (meilleur de N constructions gloutonnes),
    tabou avec durée aléatoire, perturbation quand la recherche stagne, budget de temps.
  * Niveau 1 : évaluation en O(n), test de faisabilité local, voisinage mélangé
    (l'ancien voisinage était tronqué sur les premiers blocs).
  * Scores séparés BLOCS / LITS / PLACES + affichage lisible (barres, tableaux).
  * VACATIONS SUPPLÉMENTAIRES : pour les patients qui ne rentrent pas (non placés
    ou en dépassement), on ouvre des vacations en plus dans les plages encore
    libres (cette semaine, puis la semaine suivante). Leur temps inoccupé n'est
    PAS compté dans le coût des blocs : elles ne sont là que pour absorber le surplus.
Les poids de la fonction objectif restent ceux de l'étude (dict POIDS).
"""
from __future__ import annotations

import random
import math
import time as chrono
import argparse
import json
import base64
import zlib
import copy
import hashlib
from pathlib import Path
from dataclasses import dataclass, field, replace
from datetime import date, time, datetime, timedelta
from itertools import combinations
from typing import Literal, Optional


SOURCE_HISTORIQUE_DEFAUT = Path(r"C:\Users\Richard\Downloads\donees bloc anonyme pour centrale 2026.xlsx")
SOURCE_VACATIONS_DEFAUT = Path(r"C:\Users\Richard\Downloads\Vacations Opératoires anonymiséees.xlsx")
HASH_HISTORIQUE_ATTENDU = "540a73a65ef98440fa3bf949d40913017ec54ebf356cda636d843f30934f76b2"
HASH_VACATIONS_ATTENDU = "463a35eff7ff7fd272d6d6d1c56900e629f17284a7357acf754aed454f352eed"

# Distributions agrégées auditées dans les classeurs anonymisés.
# Aucun identifiant patient, diagnostic, GHM/GHS ni date individuelle n'est utilisé.
# Une cohorte synthétique de 100 patients est tirée à chaque exécution.
CALIBRATION_SOURCE = {
    "lignes": 14649,
    "patients_distincts": 11108,
    "lignes_duree_valides": 14477,
    "horaires_invalides": 172,
    "premiere_date": "2019-01-02",
    "derniere_date": "2022-12-30",
    "durees": [5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55, 60, 65, 70, 75, 80, 85, 90, 95, 100, 105, 110, 115, 120, 125, 130, 135, 140, 145, 150, 155, 160, 165, 170, 175, 180, 185, 190, 195, 200, 205, 210, 215, 220, 225, 230, 235, 240, 245, 250, 260, 265, 270, 285, 290, 295, 305, 310, 315, 320, 330, 350],
    "poids_durees": [4, 21, 56, 134, 342, 610, 724, 849, 848, 794, 901, 790, 804, 743, 715, 621, 641, 591, 558, 463, 456, 417, 348, 298, 260, 263, 189, 180, 114, 127, 100, 91, 84, 68, 42, 42, 33, 27, 21, 19, 14, 5, 10, 9, 9, 8, 2, 3, 2, 7, 1, 1, 3, 2, 4, 2, 2, 1, 1, 1, 1, 1],
    "sejour_valeurs": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14],
    "sejour_poids": [9871, 1770, 1174, 671, 567, 315, 149, 58, 25, 9, 4, 1, 2, 1],
    "besoin_hebdo_par_chirurgien": {
        "CL": 651.63, "CT": 345.49, "CU": 188.29, "DE": 739.05,
        "FN": 216.37, "GA": 58.05, "HA": 33.83, "JT": 646.45,
        "LR": 49.54, "LZ": 437.32, "MO": 251.87, "MT": 380.57,
        "SR": 394.49, "TR": 213.87, "FP": 20.0,
    },
}

# Toutes les valeurs de "Interv Type" agrégées depuis le classeur historique.
# 1433 libellés observés + 137 cellules vides regroupées en "Acte non renseigné".
_ACTES_SOURCE_B85 = (
    'c-pOf+j84TlIX8g^uyQ=wi*^CwY%p;90vqKBs?I&20*nn8~Xr}u!LEP<PxOUo-'
    'a9%^EiImdDt%){n*K@dljlcdCrO0ot9ZyS%tdfJ+uDp-'
    '+p)#MA>2#lX19+CUHQ*>ohErY(}CipBE%9^Kdqfb23e$JR|cszsaC!Ho8mWAe>$=f;=4k@Z<Tv|M+h|1SCqs+ay|~F&X7qQUba(E'
    'Q)X(lL5KTvuJ{U3ZO8_<3M(eKgM}n#N;|F^Sf+%7iH6!Ov7YGN;Wk>G0x+g8^9gIJi>+SdXtAyxyWMzQ%M#D86`y-'
    'rfdolD4D^J*GUSqA~X03vPfq*1EPOEj1h%tl-wi{TZDL?@Q)?ac$9=`ED`?ct^iciMU*8tp)48C;*#T$K>72xwq72Z?S|A}w(Vit'
    '*5uRkx2NNtG#mJ1-_-EuLv>s})}mAVah_&58-EU~#Fv535OxSwUBI$Qgn2p1v*K=+-'
    'NF<}I4k2ki5Iz?6<rE)CKov*Q4*&lTinKZDfb`)T!^KdAWUa3^>OD(JYv7Y&lxNmOd+3S=^b<&3<mn4prGP(P2y>Si#ng&6-'
    'hS2apI3K+ZpadN~Tx7o?_-'
    '{JQ~F?QV}C$5G)@gbe06_V`T@nLSk*?x90I^5z!@<r^i?<1viG1nkNOn6!4u%il;cwN?4l#DPo2uOwu^V6Z26V0%O7Q7!DvTHiDL'
    '+fY3hH0DwDJkgO=;1$;pn&qna$Z;No0Cs8s_<l)x7Moi;6j_45%XK^gfi~t+H<>v{`YZ@A-'
    'YMSK*t^u?}lLUIchuz1|oQFC7M>~@o*+orO+vedwDzdNJwmKfjQ`KzDvwRuDC60@E81X~QjuJh>Vpe}tI{@ba{(tciKAphuvl56#'
    'SeSPzyp8~Bp7R|@V)YFPJ=ySyrG(|Q>>5T*fQZfDQot!sra%sE*ovJ5UGRn=21=2_2f?%g7(b0~=|2imgwvvf2B{sKyC|GbGLkMB'
    't+BpDP}(?;Qbr`%O{Ujq9M7_aaTryH6k6b<(hFN=Q?{jWFS0UpeUnAXi-Ig><3&7!b94p$;M|w)fdDJ}kb+zi+)D=Q{)|zMJKWhf'
    'PO$<Td=k#El>>=S%40lneDH$Y#6<zS(OKTf-'
    '8j#tAsH?7b%LSJ$!yX6j%i3KVoKh#yEGyp9P<=t+t>@LNSq(UMf4>Y9K_!iPNoDKt!^yvmmA<p1ddWJFMAx()hNoll(HAWteo>P2'
    'V#>Mz;*%S!c&#Z=WyId@khnv;PfYH$=6x6JF(v;cytJKpv#7LLtFBoi05Sj!;5ZF3~Y9hW-uwZJ(Pe5{uE`frefbYQ<2^Hc5u3=5'
    'kt0caE#7KdNT=t^v@H~OJ|GPWe_WY;sRjE3VM*k8Lm=56wwXSG=m#Kue6u}+x7!2(i(<?|G<uLv{_!pNm}%D{y5Z$z7C;I9LOMee'
    'v~M23XB9Uz*jE>1c@zLl)w(e(K46X(F0c7xFYPx%44n_UB+ACw_69sDU}v87#L|SlSep)_#<pqhFEZ2wGOah;#Qyp2J9|2h#W|#V'
    'FGNCEdktpplBmtmnd1H&?Dw*2p9l&6Hj4un1?(r+MvsI^|@Id*EJbGYCk{Jo9z)!g7(v{saF6*{y>t=r)GWFS5&eCe)qXqL;uyGR'
    '?vm^C%F{da<$(!2fgL0CQtRDT2}jAZ8A^VY+$+HZ>?tbi-n%l2O`;X7bWj=<(-'
    'lOczXWkpBe|dJ%wkvJ+6BC)6S0Ho6V~J;zdej4cb`yTD>FgV8l)BpRj1}L2z8wqWjR@DmvTEEg9BiyFb*;x{JA0yW$(XCDrF@bAW'
    '$UZ4Zz-)V@V(Pi#y}9*<A;{@D7~Ndfp#^lnqjE|kCbsf}o@wN~x=r;*nj`i&0psrgbJQ2DCA9P0h1=J&nxt?cLSZW@a-'
    '*Z`*O`YUL6`)bux>w2(TSM8yx$zk6t>s_m(^ehVW_|Idls0p8aTkj4HG`K+JCJ#vcxmq3>J*w`P&wp=w;kzrwK|VLFJp&yIzs_|c'
    '4zNn=<^lh^f*Gt{Rm(>YibHeXRQB)l1(RHR#7qT~%tz$X2IHI>MU5<{0yN4s7d~urU`)3;=RhE&ET*Q0G62bVYRJYYotwQvlD-'
    'O)@q#kHbKpKvHU%XF6)80gG9r-'
    'QW>IpJ<x@+`)OC3}bIP!$bAVbzHba%|E=84!SU7QSBkOyK(vUd^#bCSOCM4+ZD18M699I;XOvv{F&TQMXCKxUQv$b@m#zjLZNw7_'
    'Df#}1S?e=6%#ox4>$Sy@`tyFOvra%06A^+9{0RB%&1;oF}d2nICjNzA|^~+HGB3I)KRMuHSKERrQsE_8Fa*PU4P8C@=G4TxTB0>@'
    'p{W}U)JQcPz0dik8ZCgLpz$fzU;ka(<4JTwu#JOKHYH`hlil5&ZKS$gBt|c+ZIGcxh4@>g1(LAkyf4<tbhv#qG_Uq>G2oy(g&h9A'
    'p+v5TLvlp{zf%4+#n&j2$W3uBe(iL)gpx#ZrCM%M)hnmf$hN(o`r`@{#f=J)KdvUL#!CpW7c=^sX61CT@6+a=Xqp;?=zo5fp{y;i'
    'Q24oT-DOFr+r)>!bYlACRZ`v9b;Q1T0T(B>}9uI7LLr!OfXgVNVYkB^**&en}4HGtw%^H7%&1^r_`vdt)^>p9hwx0VCei=F%SFc2'
    '~6g15b*I@qw46-'
    '_YQQTx?aJ)S%_<q|tmGHCp)$tQupP~A7g?kq6VORDwnZpvm&i!gPQ*ntko}XKd5uY4jy|kLfY!3ElQ()dd{HPB?w~<M7f@ibUc~5'
    '=^ebM*~2Hb9ehaM`t2pf&zTdP3D2`0$Ujm@9G?JBNv+#5m#1#g#II0V`konKydTM-'
    '>BQl}x_RVWvzTl0>eH3yKmB<DY0bwK#4ouB{uYo~3_E;6j%+fJKx4nSG|6A)?8<U(bEHth(yrtP$PYKkgV`h#49rc4ibGqqiiER7'
    '>jCDEAJWl`5ad*=n`DkIG@fmR&#FAg>!m-'
    'Bq?>e{jJ3Ii{6A@lqOa7T;lq(oy;mX9dUx=F6%{CBkc49Q3Mf9mW=sG9`W#d5&V;e@2)9d3w&sj;~AKp$-'
    'QQCxn?W(4zBe1?>FbM%OmVe;oVTo^_bt&88Lt$%WvT(eIu!c^km<4_?C$ARsc<MtREBcMhg>rFrqLkHCbxqANlQ|%J^B>W^?zyYJ'
    'aD9!m}L!p>C4L>Nmg$>{ojs(ymFYw4RJ9F$Fso8><1lQ^dFcwM}4nQ-'
    '3TOf57id&!?PeqSf_E<lEYmp#06d?iJ^*1r{6fB=C$SnvBN2GC=4jsh?T5gxiuU`UtY7X)Knk#F2nCo_bU)`_aAD{Ns@^IV>3P*<'
    'uCfjz`pbhs3|G+DI@93&IeXfs(T973mSwHjNp1%RYS4b}D@8_<c6|FHmeg!v{r^z*t57<69w`b_|;SS3}ClGLqC*gd4cShwnL&5}'
    '71a~S5b9!pW?q8Ys=JiH8J8=#(aM(KsWVD#ymAOPM5JYIu<VLHmI0cG^p)OPIRB6Onz)eDBR3s&6C=*jq*8$3j=9kqkEli7<v@Ky'
    '@IPB=Q%MF%51I->EjMDKR3)q-'
    'D(76m#I<urJ|EK6apvp`#hwVz!#mB*Q9Nt3T*V4B8&wr3?c$Qt9WtV4}?u4{viJNSwBjKO<y)RAIL$@DLS9XL*xwuB7Y#RGv#mY@'
    '#zA<no=_Tc(k@J~Bbh{{+zaDf>q*Tv;BcHZk>pj^XKco03=R71cF9xBBpbACJwQ9@G@P5SHe;{bOK<YuLsewfXr`1@;0g--'
    'ZZZxL9z_v}PBI?0;on-SOiKSm#x`i}Os<?{XJ1b$8SV#l^lr$TSLJu^k{XibdoV$%RB^eFoWJbN^A>HAZVaVe$nT2o;7E|Wy5(lJ'
    'UAD`U{Lxb5G^d2;I8<LXl&@HDh>iiW8{N{v)02neyLB)WNcWD-'
    'd2|a8~*`!ww{xJ*ZpuHMo&bq|x*zr>r!tui^YK9ruUC^+O_t5xaIoa>%<iE9nwpj&IZIJmE)G+{Cw<uoPu?G$`cp!T*VWf)sj_FC'
    'C-SlBsdqw8~J;g!J3Vxv2j)hUwgQi$eT7i^s21{R}8_EG4ml_Q%kcc|{kX`DDjK!p%$|+_KBHeNEEgWs`tc|B30Q+G9CHG|F-'
    'B04&3#q1St&k~;f0(<eBgdnAyFM(YAi;hF1Q%T)oLvacEnLT5Ak>IK2`fpN7%7$wGU{72saBgKh-'
    'x6oJpZ3}Pfs2+fWW6+2xr_t=sD8C$`t~*oHG!-F~lZKqAW?t<xf{=MS{h-'
    '_z(<dXa4n|viS{+M16#C^I?lMN4)nkaz)Fc!X7Abv|+wuy7H6@z`+Nprf0K)G#Q5opW)>S{BR(Nm)RW^+-'
    'Hne(r^NKymcur@ZgxoAkhPgz`xhpr3K;>O|sdDS`x*!kPs!4G5suLV`Uo7B_;|?XEMtQEA)&?lGGw7z!Un}VxQ4KxR}95;rzG|U@'
    '!t1uO)AbL*dC5z`R+&fWKcv!=ZqykEEegNjd&*X&9M<8DVC=erD7eh6`BJ1FCwNUYSB9MvIhj8jnFOoRA6J;e25Q3Po8I-'
    'F?Kb!9T`{U@f+o!pYuEJk8FkWqqjbkL#)d#iZI$BO&TbHF>Ny(y&tpk6cgLpq>K4^P#Seq<ySFxPluBs!fBc*>>}AL;|2JhfJy#$'
    'd=our)sl${zgC@Ill_tUTLaLl$Aoupj-'
    '$yAzjR}vnZqyV5s$4fgI(OejAYKbNyUs`bwYz8a1)q05C!?7Q(8*3@G~SRG)5Kj3wyIVYVfF4c#W3`Oipc`!Ml{7V~I;7@VP%1`b'
    'J{v7gGgWZDm6Rlx&-'
    'WKhoF9ZboiI>#1@n6OZA@)|HwiYo!CJuDIY;jq_~@Ch+9&R>2AE)1gU9=kiTT!kTDhr)qDUhM(BZ}E)%J+ye3GVTmzB-bcrh9qfP'
    'x*{J9=B5qP!;uETnFz>D3gAu|`2a`~s*+v$SgBl1I339x*gf1k^ors9G+WnCIKeq(K>(5(!En^eh8{ICN=D_2ChjoP*>gLAVxXho'
    'Up)u;y~M*k)p?_aKobLX6@Tbi90vv~A~yr+i0aP9xktQg#T^*rRk3@8`J`l%Q=4U;W!ZI_&4G~qo+sl;X&julWcVRCpE-'
    'u@tT={A+FIX<ev10QeS!l9lS1w=$`*LX!fTl4i!pRHPUjId)O)&S?BJQ<<5D7^u<=Kyot9C85a&Mf9a67-'
    '^m||xr8;dZK64_LvBTLSFN}aIMRG5^gvF&5I?=;9j+q?+&tRrv8c$zELpSX1rE^+_uYhpb3%K8(kaQOlD$)n!Hk>ob-'
    'c6|khX{qy)33P4fJ<WMj-Kv=$f6kyqpsG;pjxQ)D|Q{jjvLG1HRD@fZhUIs-'
    'X+0?T$HK{?LUf_=A3M@&kmwR>$~T&Pkwzp!<fJ{%jRz^gR9w9Sc16yodhgQ!40gE0fZ*%gL7=@i$Hnor8)=Uf=mCw>HfU4O$_~?F'
    'C>UU<NAid7<dTs03nzSOkv0;kt33>G-'
    'as3h@rm~ExA&B%cvmh5Wh~~kUF7Ij$k=Wc8p66jWd2PPT=bbVO|M_OMmC;RJ#Q|snP@2E=4*K8XmaxU@kJ{;dE`;cN9`h1{FD>;k'
    '!V?&>KPT*$5MlfCJ^^bu^ie-'
    ';k>h!KL%idSsA+<8Jr&IQK0`GS8R^CZM?!v1T*;4)otS9sk*PN%BnMdU=l*OhyXpsG8AV=D4HOa2B5sbz~g1EtT?UgA-'
    '6X@eJNlR`2^Xml(zq5nNKk>o3DM>RkT|NH2X0=VuvxO2SPVe*{uBV=4+tG}9Qd4Gm4}MdP^yt4=(-'
    'U>Y)YLU4I<Ilpo6PKDqlavX;igPE*-pq-'
    '?b2{@(*W3hc|`*Tk>aA`wq`(AQvHL6K>o72PDKmT!Vidp(bO5NGWo4O7oyfK+$lz&0Qkmp#JeT8IK##8uAkm>WV%qTgVT)dUOYtV'
    'dfo+@rc4PGRu+A6rB&^%-'
    '+DY4LG1_tEh<V;bPfXJp^=@uCxQ#l4U;bVH6BRqwoaU;>iQ61Ve?LlA64oR+=UO1CfOn502XM<nS{K)-'
    'oXrkfVObZQ>=@v3Bcc>8sfdQ2GYo1KUDN!-tlE)liEU}vR8VF1CK&as7nS`k})tW@re%I8SAAY?2Mf-Kheq})oBN@>U)%)eTdZ^L'
    '9N5dp*9{DL79;@R$V1U19;9^Z)i>@MOOADC##b}U0QY;`XvZA`-D)0dD>PVt_s(ED5sMy-'
    '$@NO6Y2D90%E9I7de0VybM;=fvBF(MOelI6~RIwH;>T+U0EVqZR7@c=8eqGg~fg39o-'
    'Uh?_wmiNaKd}2NNza|oBo%>0(YE>Y30J<wrLF4YzSVceY(4O1*(xJO$o}yBt=Y8oo`%I?v}(%(R0Qx5Lt(k$mh6u^x)4pfd~CK7W'
    'M3a}S?_5K3x>fz>}#9=51rA&-'
    'TlCi$EW9Sm=Z7`^%D(TL9pfaxP}>E45B4;X^0q}Kwx4qG;+m97wEt@vTRjbn4>=64Esjea|#r<D5z>PB<V#!20v@&bYdqjT3rMo0'
    'jV{n=DpaF+l&l4zYT>~T)O1U@F+8i#hj+<@BR!&`=O`N`XV0y^`&*=ab!PKP-YQ1AK?E^hlKt2qMH~xng|($1)XV$)wXZUSU1d<r'
    'EU_M(j37wK~G3!E3?N-x*A47p@-uLfN6Hk8TVLk(IYriG98ODpKw7_0{+fCoTJ4|aIuk<+YM*XqMi&wJD33S2Qs>{4rm-'
    'r;p1q|(pfiWN#h$b<^>A@7`d$90~>UKDQDwcka^5xSlNYi#dhG$p=aoE@;0i(hd>XE0Zu3sRq9^C@I<&#DZ3s*lH-nNi3}CO3@vJ'
    '?){aKeqC{W3mgT7(Ayk3UWH-)X|416;WEzR&5&eXkaQ^~K-'
    '~^fhP#P_IkWHN<X+gb#k?@UW38E}P);=iHYhq;knz6u2`oeCYgkrW%oR-'
    'u+&eTIA2H?fLkrHTPs<3Yw8mEm6?qHIN8WH?58os%pr?Vk$VqYv8AVS69aET;Vj9HN8Bcp&v&u4aTb`OL`Y!;f$O=Q*gt!HOBonR'
    '`^fMxFHAhS{)ME}KQdE?upeat`<xE9<ns+!<R#T)6=knZ>#4XRw`mWrSBQad(InJ0OWx{8<?_%|#9%`#EWd|T5(qbRO%;Tg;E!Dv'
    'kfTEUW{cmlZh+-vHH`@a2aC(kp8ex{7gG=1-'
    '8H|h6u9U#9oL|9T?@Go7r6IWF!hGqyL+tV|>pb>!&kEFR5tKG<u8f)orC7i>!C=+hf4OUUntxVJr!TOq$PN*7wmxk#$(bPeH3D1~'
    '9N$VNSx_OAFx(_W|nhnqEBq<?_xsK@3>~t~IRoO#hhfJ?cEZjqhabW`bCT)t|Cx9=$6I6?f@PR8`nBg8efW^njDPMS}VS)C1n+3`'
    'D!iIHigL`>hkaTzr=j^+7V%9;-&m^<j>c$UKh|p_1$N~>QbwsGNS&YMk*9u2uv~WbHDhI&R<}^-9|Kz(MCcvHgxUS_!3z2-'
    '!LnMh|V(P+8h72wjfJ)Bx##=gC7%kCEJq}BetDBMJ>x%Ajb(&^rYHMY(5E)Z_*te*VCktvs7HFYbOk<cg3rWQJGkL+C@+`W>B18|'
    '#=+*q(4aDn_um}m2bL3D~&9Y)9;kL4|Oi*LSAQof3I4dY4b4ilf2Vsbov4FZV>BMWKv8#e<PFPF-9cPOYYh5vCS++>|J#+SziPX-'
    'ecMi(AmoAD~5JfaugtHk!QQpie)iBSx1*>nrmIG~~<@>0S11guj9LS`40u&SgJesevB=#6i)DhCOO#_uG>W85>(o%2j2`K1zAEn;'
    'N3W%MF0%B$@t!|}2)4>VkzKHPv!5w?e#oi*0-'
    '*~%s%Ru>x5k3kYwriG;+s*3h8qI6UI)J~+pB0hXHM_^JZNu|mnVqXW?##rr`ryb}`!Xc2@0&FZrL5NS6I9iUN9a-'
    '=wokQY;E2D}`&#AIiPSaBfvN8SjhwBh&1hNP;xD`PmRVb+WkdT$Y^|8(k>%f+9eJ+qAK(iQ7*M*Y_n+zbqf6UJqJguzH_oP~?Y>3'
    'p<!I=f3Ws9T)vCluW0?zz!#KxdFsu6XXeR-7)m}{B1w&WQHP0V~$-A35FRj|UZL@jMGuq-W2W+Ed3}WcHsSk(kSH#kprw+(-'
    '=w+LhmHGVb6Nh`M{(?uzLUhCJQP&|FJ+7>(WYW#AD`t%R$hcf!oQe;*SgQ%IG+NmyZ~)G;8G||l$^x2K#8M|<PSd+MwW@j=Zks^l'
    'j&<kkD!E4OTgVZRj+Z&7(?a^hh>t8{@kPH!z!%8HNQIPN8k(;@Mj&;<o8)6i4Pjim3!Km@uY*U(Uog}`ic&^6qMpQp#Ve@s40oMh'
    'j-pdwan4p!9`B5mCv$T}g`E<)y)IH1yhB0_X}QdjRjoM<?h{moFMuNNt(qZzc=zD%g=_r1v)Sg*T8!0zFO=PdXHZ}^oa;O6tS2i<'
    'DZ!$3aVgRV4R5$6=xXk3%@UGEQ<-'
    'j9V6=g*C8;#lOQS@P7B|*`1P=b5Cnf0I)LH420(+{Rst(LU?`d36LwK*?Y6An2(muuk#3YYI#$b9x61%5quNjc{FqY*K?sicQXwQ'
    '6<sug=6G^%Gesr0gQy{eOYGSdqpFS-Zf$~}y^qCjz_HPsL*yScsY0*c-'
    'o;8X2n`TRe?DczHVCAi>JMk}EedWN14btpH&p~J$jS}){^`xd;D9U>E1J(sJ~!GjlACvJecuF6lRfKclX7vk_SOlKz7?({Jw_TWU'
    'jYwH~#!Y9=QW&HDFGQ|iTc_}>~t#5@%Kb^(VFHV8<goDbkQ6pB!gG@}fZ%!vN!8*N|<r3|!qZl9~%J|*DgHsE~%6WTei$x0Uuds1'
    '@?mL>9RH;&y9_SvAx=BFvqbfH4wiv5&^iXUXL2BGVtUZMiE0de4mWC=1VR{)B*gWvEJMV?edm}{Z)lroCWA56YY=C;#Y`D6#rm1p'
    'VPqS)}Ncdf&Rk>otJ_4-0rAzd7A5m<uX%Ceut@Qj2G>RqG@_7Cm$akOxJYa}PYxf4Y=74u<P3wNJ#698oT{YE{qr*Y#Ap><H%-'
    'rLJ6J!lf^7KTDlE5l(Jlfs^Q^%^w*9$EC!Wm*GK3Zj4PR3JY{@J3$TqRM}Toi;G(@d+f4DEiV%0NwXP7o2*$m7i!wFzuc;hCZ)n3'
    '*hCV;p6()V5xW7p4b93Z17|)&PDnq<`l04%}GuB7*#z`v6%8IYy`~@*9?LI-tY9u&+^+;JbiJy=n&4Do%A5TljK7n!hPEB2Py%NQ'
    'WB8i@DP`W~XhMc%*st6+a^VP{I<(yivMI%=Fkgo#*)}+|0fRC{Yy3$SfNPhnnR<RNAN;7k?7N*g3Yqi^!_g(ud42=SjaX=q@}(T='
    '@9JeRZPgilFuxa&}YioT&FEfT)BCy`*>6lCU^#@l1&<6ywBf<O^HH^Qi?kjwTsWgAkp;W@&d5ldveysdK{=O-'
    ')EGA|^)W7f}nR(#hNfbi6oJ9L%j=$4%P6^SN5&tDZ&f<dFQvFarI`l%3(k71GO{h)Zl`Wv5w$h0VwCcgU)6&;kHJ>l0<hu&}C-'
    'E|WCOJ<G$q+&D|&>E^veS(ei)?24#(F(3)P15}dF{*`t2oqW*0q=y{%`kz`vPmk|iI@kePjkg?sKL&kZaz6Xs9v3g^(ZeiVfGSFD'
    '__7Y}1Hl6DdF)A^(XuPz`lUD1x#t||iUCSi^hGJSr+GGp?WcE7#nWI-u8wVy1kq%A>ql-GF>lq2KLL47%cs0K)fr`w0TYTuT)TJ^'
    'NXm4IsBolxAFR;ok`@!H%-'
    'K0{FsVzBMSPZs>p1>9BYB(3Sd>%my*g?S=TjQLfs&xj>iPy|q9e26@M%VqoH}mD3)HM^DPVXCr5&qdZH1=~lb}R?j+Pb?cseL6Jl'
    'k2h#v%06rDNDBnkaYz4|lfWalQ$Q2xJf7ccD@C?F5DldtRf!?E{p8GoLJM*sYs&Yf*Dp>Ri5X#Xc1U{X$<{QFupxKS(}qq&T%>D7'
    '%mwTLwJ|1|?j*M$@gC4&}fpg*J9Gze8|Cw;}cXtZMQfU)uxAyLfv3wrScWsG?ZS8MNQ0W4i?9m)BC(l;Hmbe^<Ne@aVv;rtzCmev'
    '8_9ip897ile83<@@V&6IngvUUMZ(67={Z8eL}2-'
    'PqSWrDC%sRkN=5dgbnB!%A5TO<Cr4fI7ZZs&W^tA;qETy&DXTTda#zT0t~%cnTNdX@Z5XPso`zFULz-rqG_aaiS2Wgf9=s3uGn}?'
    'xZ*na1Gjdv$PP^n0h*hFpCE#M54g;QXR!<G73COn1-M<2`koE56RZ?_dXn{7g?0^fZM0d!-'
    'djt;+PtpI2ahowMa371WhiIgL6WG)FX7_ej#-'
    'Te4pD<i@7SKCu`o~n_k_BX1atfxh_bfkX5xA5MI;|_(xKJ4#xeNUaip`5$&72AJ{2x2Ea_|r_kybzzOD9m?uf;)&a+aTT;Z-'
    '|CUaRG|^eZbbjN&=RJx{4w%#M)af<#FY@@UvvEfZ2>kM{sEJ5@YaRB~Pd0s%>!#&eVwx{C6%Qs$;zuVmoYolrxcKSH;#y+@+i&i('
    '1rSm%b9JcK^^(>0M@ri)(FDt17_d5U<K8*2r$ha;Gwb?dpba-QC_4jn51OU~w8T%hZPhH@q`pgWlr2<~T+P=Cffdm@xEU>z&Bd&s'
    'M^<#=EH&9^ID09)AGK!sQya~mjqBJ!UA^SRV%b)m6XWJlPTAUp-leu#aD1RMRD)gs7sXvgfo}R+gWS3?X$7B|;4J)TDA<JD;w2>F'
    'lPEv}x{J#RoV*z~@k-'
    '%ED3u+pj$|KiR2?V_x1dIJ(>);GXb&4uzMN}tp+0Wj=_`a<>L3V#aox}yM3E9*E@m?%OPJ{XQN4DY6_%ro3>b48NcQHCY`jO@oD9'
    '<@zo);P6-'
    '&q0zNK)Z3C5Vz3KHb{>vs3pteY0SD`wVP{}@sSd&y$!<y9E#V43hp(!}TX4t`RMqzNapGK}~WgzS;Ym*Pahm$)R~Gy4MTf-rq=!B'
    'nf=Bk7&o3b-o!-_unaPrsu4El@mtlKvn1ZQ2@o`8+SzCo%TBN0ZlcpEP@1AD9wqP-'
    '+)~%?rS#@IHJYB<k}o#~b*Whtt~jqLZ#mAN+<ezIuz97aXG~^CFBg4xSW<C^=dyb#@z`9`1xqsw;LXH={?+HVhbrdVpQMrQ$`D_Z'
    '<q$4AiIlJ1chdS%LJNI+|x~Ezv2#L@SLKO@8Nb@SY)jLh0b7`X+Z?auidv<_5L_oV7e2WwXB3{2mn&4x(WxVlLr%dZP|p{~&mneH'
    'y})OIZCzLZo)?F{siPoay>CIRVNwiZo69aQ;hy=83UJ_nkNl7dLzUwMXD%&ix*#MO73Mr$qX?cp<k=WpJZ^BwmCEmU)ZM1%Oy$1x'
    'zWsgk8H=j37$+mbVg^X+*F`c}Cw(q>_Uu{ena&Oj)7bG>ZxmP$7#8dx{7-4-'
    '++^%8$l3dBj@*E@%&(cX_Eg^}x_P$?X6%05uaUboo7nGY#aD!o@ryN>HsCuYwd{nP*4O0PD=fIcDGCLI)lRlV2q!Om15ypM9nBnN'
    'M_Z5B3uM#0BO?_cB?@BdnaIH}jMW$S=X}HbGt*@xLYl<B&)Xx;L}fat704fJLT6_Vd$&yj&<SnDiOdf7p^toxptutRu>!F$2iW=z'
    '|lL9!ousgqBnqh8jE2zk@;XP#FYhX#y{hGz0CH)4*fpMUfV+Aex6*Rr>Alr?)N?FSMnJM*~hUV0_%u!#5q~tbb*MB9x5LnVxSV<J'
    '1t=W;(w~13!5SEa6FjyFh(ksPBe$yk7X>nicO=uN6<2&E(b&fBxz1FDA-p;^5Mj7=NbMchLiQZWjb!30dR-'
    'M%5Pokv@5dG=Y#;Pn*&3p7*gdy@`+1tJXOCP~(&t$Rps?d)A7cbo~?xD$pLHThiBGpTEiHU%SA-'
    '(NnTK?msuXb)^iC+Iz03_%`>LuSerhpT8}!me~Hd*8@h85%L#4tG{+EVLG<mcEeJzu!`C4@L)UHG+2-'
    'wj{8;^Nk!6NO+HoavZ?Tgiqvg;#D^!>)w0&89evWl?aE@sxt5smN2|lBCrR~otTTtkQd$|zeARLiXpfk6B9{gP`0NLv?x5vi;(K<'
    'CN<`XK>;=|x-KiDBQqX$)YD|&eMXo`G*BG4-'
    ';*SRl2GC`t_Hu}FEZCsPImUWf7FD6n29?hak$I7Yg;SZ;>S~zX!w96H>xB}6b*2?w=Zh%_t2hakj5IHJ0HU7JZ(-'
    'C&HVUhtCkoWqI4^`a;Y7fyLMfrVGe!C2f|w-'
    'Ri>v<+7)ukS9^TW3(y@vibT63MOVGHMG^X#P{p|gI&n|oqZ10Zw`doN>s56UM_U>cL6EVKOqh)sF2uxFdkugx66$hRUMhtPb$WhZ'
    'Oc_2HDj*L*3C%{ZX<`r>J61$ua>L3Fv%!<}ZGDSV{E8KoOx7rh3vVx9toEI(A(6>l|tP6sgN$>)Y4%KB)8fn7E9nsrI>$fo~S+E&'
    '|$(U-qguSVB#-A3WuV|naPJ*Bni42nwNiWaRE0t@Hzg(RaLS>KzHayi3CLlp1G;@#&i|;`UX0II!-'
    'fupe<aoztV3jYI7Nmhz5&jo_X$_2lBcq4D+!V&YEzmS#2!2*yDgoVcvk@&KXw>&IlN$JEUv^uJydzf=abx6-'
    '{P_R_ME+`kN;K7aef&ahtM$VXw(=eOjh0Y-&*Yf@O>VY(RvL6o3mw3}*0Q%KI4d6h77g`&gSq%L0I7EV$c{@-'
    'QwLkKc{ny3ijO{>n@q7}eo27$CC;iUszM39VloGT)r~MRtMms`n9NY9aDl=q4thou8_*ub)JA5-'
    'M^!4HS*H}slZG=7EHeVJyGaG03@7qpST2g6hNrW@`dp~-d1uot2aP(2{*I2-'
    'p%_t4gV>AH5PE?yQBU3mzZ3OvWG7=eor83z9iS{<lf!>Cn@`ObS0~|WoGuD{#SM86bEX$r8uQZp>RD6xd!owHOOj|H9y=y)0!YQ}'
    'WgF>)7sm<r(LO2u4!)gNc5Qu|IC^x3nM~B^)K@mYu%6v=Ed+flE}P9{h%_&-L*+-'
    'e85Nc7d7jLoWF8Mc@Ds!=o0p#4Y3@p1L@Y%znX^I$Iwb6?2=TlIZ3KM~Kxwq(60<;&e)FyJLs~679$-'
    'U@7dgrh`8yhqguGx#d_(v}W9a$3fg8jckIH?2qA{k$*Uk1brbo&bx_Kt$P{Hh)c1sR>R4y?mazJLFLT}e!L1jO#H}u&;(OVTKN%2'
    'I43o?2Ymf@eXJKY-zZOJS{SxJb7sycMsfyot6pg|28)U7IJOrPG&qQzX<?&jydTyoJ<s~xRXy`ml=mWX6V;qY!EgB__?xG3@L(Ha'
    '^A2QxOyNHUyQZBYmpDaL?Bk@qYk@HCJIWdRYtDuc4)A$Q|5MF9nN1oBdjq)Vq(nFS&$Ke;evm>eq89_&WV&}XNt^Yk}GUOSz*J?Y'
    '?U$FjffI>H@L@!}i<b)`smx|rYI4<&13skfgra@y@=-(>QdKjZd>07q-'
    'q^zlzD;*JIUtIeUs3ivDXU;Cy#s3$vH`ex@v@b>3mI1E%w1+RJLBo?f#(B*YLg^!{vzRVM(VR-'
    'm}soh|>i0rS!RC>%Cms~Neo|=uYgE1lS8jEP@&07`}D4=MOEkl+}tG3>gc(dA)+ZxavzsQEqD5|no1>(j`{nkx?vrlBf$rF`pCCI'
    '0T%6K0@nAFJO>#nAuuo9F*+BP-WAW(=W6Mp#dS2q9+uswx^S`$H|V6Qs3oAK^x;gmqke|hJGE|%5qaZA=mwgmoB9{?BG?hkddHi='
    'BL+dfsSL>VvXMP4gwEhq|C<PYThEm<RA-HK$T^vG)fRLebV?v^aq)#ql(AGnqCFss@aMe$EV81VucTwqgX2S~&U`y}}yA2XMR`80'
    '{Dtl*taK+B($AV|_^^U-'
    'CX&n68=EZlUom@n?iJf0E#VO`6&E8x?3G>UWj<Zh?fKMlx^WVR_XtvJ<dLFxCiTjp7#dRVC^`EwjDx>f9TC_8-'
    'KsKM18z}HO_xS+Z_thJ!<=JuhP1r5YK5iu%Mn9altx{$SV#Jh8_`B{FAk2MvtkhmO8MT8lJKuwL>09%k5P&gE37M6zJft^@2RUKG'
    'k8m<t<^yM;qx|TZhfs#%ass0Y22^^y<4xf9+gJt(X^G`CL!2f6lGR==JFzVhRUGkB>9K|Tdu0AxoSBiK&!EDZ`20lbjZ(|n0xrEF'
    'MerM4ErBMZL6N%-h46s|V1igq3Ickap_0(%R=U12VSNW9A+qaY&Pw{o_3JVJ!$PQDG9-g+H$9*W!^WPX$b-'
    'x6bF6HV+7tHF_aZ{7^*C!y=%jdsSZ_&~$ZGxFzz&~gy5rJZRk0Gs$%8mv1YFlmBbO^R<z80L=MW;o%nTDOVc6-'
    'F3Xn;~>@FG6K{s2%zU=A0gZg==W19AX_jMu*(T7ba?tAeP_kv3d3&wqca1q!oJA{BdSc#C|WN`}X%I^(tos>^@f2d>O|*_ig^F08'
    'F1@JrslX0$f&VpvytF)X1<=;xc><A6xD&VkdQMBaAiqcgHBi{wQ{fAeF?GP|P+(`?pNmmE;K^}{YUX8M*@FXfH1GyxUz1gl1E5_3'
    '%9=;%MzY~)*J;-'
    'qkkQun=f^Q}6AKU+_t@sp)*sH^@oP*<#REXsxT;xaygmGU<}Q8S|WKhgbMn|<V6;4WiC=K;)c<~?$^)HLS8XadT5sLN(q9rn$#W*'
    'V`)($cD6OYYi1kT9Ei|4Eu3mg;dXZjkQ<G*ku;Bnvp`hw0)0f%*vqU3@!C{QUe4#9$c~V9b;P@Os=Iha^gqSvCrz5}#+(AKwwv0N'
    'GGEHn?nM_!^8T<}OL1o{?^$&kl&FULI0ky7xF4uraG2en#tun-'
    '!tu6AaeN^3KwmHjFmKz#dzH$ugaiM_K^lX%#7cSbjhea&w)C(uQ4vVmX$wrgLpf2(<ZV#W#6HHTk?}_fa!5Sq-#-'
    'tYlls0)%*#QNFCdU@#^PYIgS4<M9ot$_#_nI&t)YO|2c9&O@uXjiu+cGgVVwbT4o15SDE70CG>VSynWa@YgH)V|%Dskv1%)9c|ZS'
    'bR;+R6W*(fF2J-?C);Yr$MJBGPc;>*;IN(l;sq;?I|=sA0X9d`t)yk;P-'
    'rv(SSXWtLeVuL6GGBI3c#oY;$EW*4Ly2X?E2xycb6PYt6#^(Lmi2ux}Eha3ERWIdZ2arT+=XMM;BDkTjMy@kt~k~AD~@e+y<CloB'
    ')u8!KK{kh4A7qi;vr_+P<8E@QxtN8P?`{VEkw_M{FM^UO3U<HC-TsOWMt=rosyN>YA){ZNdvJX4mr(yk!3P5pxQ~+n@M1f6Ua=?e'
    'X|j<D-?{8Ovuay(6Rggy)f0cl5(a&x9fz9)S7;3K<h&1F!=A*2l1$tZG_vo<Fo9^d-a)JC0-'
    'y0(+hmUjLV9k1`sh8#A{45<rLFT)<4j5BAFywB%k-'
    '7_gyctKe?^=^lsFXlG=NNC?_}s_|!&*#+S|qmrh^9ivH@j}^k4RS7H>*H~gCiY>33{?(W`!JRu;%PA(p(x41)l<CbEod3=zVT$>P'
    'ylAYF$czqoc%79cD?7ua8<TaKz%mcZczH~Nx%lTl#A7XXr5b#e1RY94taYqEHGkGcBcCs}vTz+W1K<=8njI2AuQ?Zi0`59Mlz!~i'
    '%;>2VFU>dyl36I4zg@$NGDuFNe|}ql7KwE&!hBJ50i~=FnBsGGY3Xr#A3j+z`H<#(@hGWyl6HGcL6kDBhBT4O4qobZG=;K1<sm+!'
    'G?+UMTmiD~4LU4G*>sv2(Uw{OFOmr9enSOq0LLzhhy$aM>vuQfwI$(PhA4JtB*Z5Z#vu!i@Aj4-M-'
    '#1YtWYQo@ERlZm@FU90@rTJ2Wj=^bl~J>L+>8(QYSQFYe7q9Gfmx%-#FQU^U6sWI3xVU2n^Xr08fX>EnQm27w7R9G-6q;Z8|@v-'
    '!W}A4QZE6?fxR_jaPBk&PWK)RMZoeJnn)8exQPpq8&LOSp{vhzQ5xgoDR<}&Ms+e9V|gIpYyfvfP>&4j<S->wATf-GpuwrnL6hyK'
    'q7+mKvQ0Cm;XUP<i{#b5BmzX;1&*FJm<%F#9k@Ekj>#w?}Fh^zmm^Q3u}^Ri$6(VeX3*feleZ_M_{XIG^q+4J(sgnnIMY!JDO~l3'
    'YM^Et&rAB6hO{A?bZWEPAE}SP(1<>xZvz7K;GMjM8;AgVFFf_E<U=buI{G*EiX@IH1OsIri%F`PHN0iJ4>ZG;P7M(|M?Hax(Wx7m'
    'UTTFW7>>jbZ{*uunE#HFqMy{cFz|DB%ZZUPCU3IGirrH>Y;n-'
    'EpW8>&d&$@x^!W*yc~1`$%_!UXTaQyhG)@5?5yWE83F47NMjm&C}Vwjsbeiq($%X(R~VK~Ud+ae7;D}*w>i+0!^QfQVP3G(;QnQl'
    'F$KaNVl!j9yT+gs5;Yr8h+)g0w%bj6*lubJdca^+L)V!nbD%Lk;g-'
    'G*cKOoQuF0B#bb})d+YNIw@^bfQB6oyE_8535CGInV>JO$FQg-JdHKSn^_dO%RV5}gsVKBPtK5nSJre+H6+AC`u^@aLfVl@DU8i2'
    '!uELv3jjcP#2+r2*gNBmtYjuo&aFBmZ`>_-'
    'nfZXPTA&3wSF1MRlT>+C=zFc9yU2rC>EAT(r)JW}<an2tjqG`;~<YJx2?iOED1xF0}td~7~hpn+Dsm6I>#TC$W8_<R932*?ne=ZP'
    'PSwGsRcFDbfF6Qp{$(Ea?R?54j5c4j{QWsqzW-'
    'hLNRCu=@P_q6p9iIHE~*1H3SGRhu!K$ZJV_~@uQ-F4LQYzN8KKqIBLUjE=hGNX}Dx*=MEP-hrDTuE*|P#N2xB}{6f-'
    'hVZncg7_HwZwii$x2^7*A)pP&_x-=O_T<VV7q)-IC7DTBXTmxJQ_LstH}*?3x!&5bNf7f{qwUw-k#yV)CuD-'
    'fpH;(S-HVN!(pWF&de{+S$!GF5HbB|pktn!;utjro!Id7QwN#B4Y|kcO8jGmu#8qOu9=^@^Q<tf-sdjgXUC)gD6jOlrqO%V!8X^='
    '>*j$bi^$@vHj2k}O@kxEi;=1YUHDqK1v6;VU+Gt4WE=OhflftDiZGXk&0EJIgEKC#ew9D6tm88+p;$cA!rtKgqGRCs#QF0#bj{JI'
    '1{yE-{NF1YTezVHNc8drd9_mZ9`QKk`aShp;H#nHDHl*^FY700-'
    '8K&g!^Jn}21GH#@P5rADQKNv3B)sv@0;zeZJa&?3DbS5l;Mse35m9F_^FYJ)buC1xBKl%zWFq#uV6m^jqK~Tt&Rtx-'
    'a8c#u+h}*kzf(tr+U>;=O@cA5+_l>l-'
    'mQIEENwqymYn4yXr`zC4X_X@;JzMzrJ&|%7NdRofn%1&lYA%<ECqf&fl3IvXYXfwzTbW#e-RDeij-'
    '%7YcbNT2bTt77d`Pc7zIA2ny4xcoCR=rRrjv@j^5UjTT0c9^NO-rq{v@Clp$dF$J7tN&-K;Qm!$)-V3LdTI)ol8O++zH8H}RRU-Z'
    'HyWq_Ty_4NW=R=ah|6N##`zJf5=OhJLsAnzaNY_=U9a{%n2+<>s5{z~xW}ahzD-2kiOT%`jzC~=ku&5rb6c4;&sOBhkzn-'
    'W;`<}t{Lpl@=2bAaCNTn=Uk8Ad!;4HH6gX)n9Mr5yk65ZV}VOF`N`Q(J--QU%cz>RS*TqqL3@xocLFwAg{=f3sORa&kQiy_QWn8?'
    '*LcpXSq_D#qj@6BE5B=C(-w2LWv;e>$5pKbEZihs208v;N0Z;NmQL@}8sWzQGe_4vGVHS^HKjEz?X`}%zJV-'
    '^+>ObZkTVv;T9bLvqe?>mV@S~5OQf{C&Og-05#f$CNl@FvRL`mP2e)HgV;R@O=vwm=#(5}~{4&4g>KR0GxP2)O&)MF0Fd^cy-VsJ'
    'S0dv~lr$Q&Y7T$YP8lXWa|nvL6U28B%9tzIT8Og1f#9)>oz(NkCer0WGJme;P9D<)42SkJedl1H<_ZOAJQuPET1FxN$)ge`EeuVZ'
    'XJK7DR8qjYUHAv^nmZW`w|3K5yV$_)ToeCU_pxr!7HP=sYGm(1U<F9SskWQC=uG0o%!hP=G8`NtD+jsw$lVVK2P#2sIUPX1Tt^{^'
    '>?d$4lq@?YZ|!>{}n}{WfXB=l}vAg>yg7^vGB(+)vA|=yZj3pOvxiHE`!>Wn9K)P;YnYWg5=ONT%o+Z%m4s*vV|%y~(2FK9G~#71'
    'AcCn&%;BYTU@@XgMtkZy#7JICb0`#o&cyNk84*ycE+irh*MlG@A#{2V@=w3+j~(HFQ9kys`(MVbkl{vh!;B*t8gX^BMJfUDLjBwF'
    '@o!-IdmwZlCU{ey8>Rb?5>R-'
    'LKxg)tc9$IUqYj;nbvku?%JpkiN0Q^EcUJV};ZLhHbk8HP_S^z6;H<*3n?$EyZB}UlA=ID;hu8Y*x+ZW_3iPOYl^&T#hv>A%>N|$'
    'hrdEob2|`-'
    '#*uyqh=_|>(!BI_~M0FXkZbBs!1f+f%?oE_`^B0+?nx2Zn)`~Z}J+prC~+{VIC3H#b}x(T*(KcsMzy=V^y&M5rz`}=!1BqC!lKpY'
    '85U)8+3=EcB0xbk3D9>(7IcfL;a_+-'
    'mLKJ&WBg}&nj&E53my=m>dSF$#zGxKDWv)p=tKr{*LH80kks1(<Py+Ve>v!OB_+yABL>uxD$^TALzWv>QxBm$Otm*1Cmi?0?3KR1'
    '@WK9YPDZBZ~*b8V$%rc0&NhsI=mbf@nTgvqy*33VAsj(&kY_JI2p^9RG;f5`4Az<`S9`bN+f^+`w&MJzF>dcKQMFSS|o-'
    'h^ASdi>LxO+560kb;VM1U=5x>ie+ZerqdZjE&stY$i#rc4&^RU#s84mkhI&lt&<E9xFm^#zpR3Kmia~Y3=~0O%fn4)4iv_~%#K*!'
    'O@S5^PqA?yA9F}z!T9J#UUH+xn@)%+xDAWL>314Uv<2k%ud=~jJ1#o3*rP9Xo`G0^g+PDl5U;leJcW|PX)#mwIz44*2pdR$X7N@|'
    'F+(~=z3sD;<(qUCTRQndq<%V^+Yi|9X&c*_<7zQqozsEqb>68YG4XOX{y`~mQX;Mqd^(FV()$CbGlW~Z)3L2zIOVKgm72{5H_n0w'
    'G+<Ex-%q&O8yWDc`I;$TNp#e@LTGJrTfNM>rZ=nFCJsqJkDJ5xti>i?(16-'
    ')9O}bDt309O~XTqp0ziOISX}t%hJCn`&5F90oe$f<YD;m`-'
    'erbuN<WdylE}h_1F`$MihYMaSXoL$a9uIY?k&ePm9{ZvLva=Ok5L!8?ko6k10!ON(U0`)D>>&)#yy3Dp6E8dIC|+1lci`{IU6?NL'
    'h@)vlKNG%gM%`^T8a=@Ne)hho_U=v8kBZ8+3iNsqAWOP%!Ib9lpR+T~xH{7kUR8-'
    'Txk5S?+!>kr&V!S=XZ%w0j4P*ZD9bh|(N<zg@KLujJ^kFZ5*}|HqnE)cs4qbDFk!egwEE&m`RbZizyJn|zAr^WzHWe(pa-'
    'u;E#LwE_d_@N+5u(d;3$ZrQT*2uyJ+bp;gr=gzA3vk-'
    'b{PY$_%@D8(D>v!IfceXqjq8O9;L#h0mUfJY2JWyk=BzDXiAUQ8Q#Rwsq*CXp_eP2^6(JEv7SJ$z-'
    '~{iwqfEg&E6dRaIp%6`k)m#Wf?1c<v#PbrYyAV*olHP>JrMG@Bc>)^8K}d>%DFbK@!&0Dpa5Jsd%8sX?g%ss4?l9D&_sU{nq7R@='
    '7W`K1%?E*dv0bFe+d((QLqda|qeHGMIlZt`FRNRT5Tq}Zi|1Zws=<}D4x0J*`sIC>O$*9sz>s;)yMnrxFbXq=eNqb}4Z(D@%5j2h'
    'V6RH8JKead~cX}LQe;{sk)I}pXOmJUW&wDlT(kJnG_x<R3`5}tpn*11a>rkJG`T^{d2+osxXskHl=lZ??(__{CHazB6LUxXb-'
    '7utNWh0~lBY7@}E4aE2ci4pP1%3VmytFV`}fKyCESWt8EZ!1)s@#ehynR@4cuR%-P!~8Z>JE+XGxeAu-'
    'Q?qII{FGGpY;`_0U#P*ydSJ4;Ut-GR6<neE0Lu7&S2HQln6_NwA=iak&7ZF?umr3g_SL6)fI;UDN-'
    'M#*W`*xsPUmh+9AxN<0<nQEUIKI}fVz2mHt3ZA?VbIVfskuEuSHPY8-'
    'Fjg<bCr6Ku0Ml8)|;h+w92Fw?S%llzJD0?Yby{)d$*=;g1(5Hnp|(qHlWb3qGMWxAejZveP4n<R$R{iP3zhkc{=uNTez@Ej20i!k'
    ')NOCRqO_JXMsCt)=O8usrTn_Nauz3wqgmYY<{ZL)`Y;BbL>B5Y`A2-g;krurng$x}3Rs+O~w%p6&dstcfc<mXEgCTf<t|(-'
    'UjGklolxc_<*p!wsl>vXhZ(27n<XvN*8U(_|3E1D&V6arF_FhR%Yp$qjb<X62SYtM)Ud-'
    'SSVm2dcm0Ij$%eE0fS(S*LkVY26c9zy{uX?G26ho=2qkgWD$Sxj!E8jZaP(ES$7S@E_w4;`1O6HB|>dl!LFFgUr-yKEWKIj{^uxC'
    'h5qnHin$M7FN7BU9jc$@O7=a^C&-'
    'SR{U2^p!YS}_vnH$EA2okG3Xjm)}v)(mL0@UsdIN*dXZj=mh~1b(`(Gm+QD$<2hzswC0cG9^b(*N1jmN*>(=^;?HY9;&O96}j8jR'
    '#fi`B0K*TQ;<yGL`9CR7T?4;i)AQv!zxa(f7w)_gDNLw2IGhhRt{b!tBm$aL6LxoQ)dF?Ws!g3rpRKnwKgr=reek#1b*JRGsad-'
    'TB*em-b{SwXi?M&9!+NGU%bkPqe?wN62w078>`mdNvuUW74jn+Ude&lO577)+eo`&?gcu>7-ScwC?HF9AY$beScL8gRdhl8`_a-d'
    'hOtv^@GBfAujHSiErxx1+~^%wcamKC%7RP)$bCOup8`LbJY`BmG|Xx|Gz+wTIeYUf9G;EW9$_P`kDTyFV*JU)MWlJTkzX+wez@tH'
    'lQnW*h`gZ2oU$`5kc+j`~rGTD0TkRnY8#}qFNfTap7cK$9&m%E#1VpcPG&83$&0~(>t$qHw!;z_7C_Qz|5LHH<_o_6=9a&pOz=g7'
    '4@v}Q=nN`~<DyYK=CDma=H-KjD-'
    '5jWm#W<^JYt5;AE53n>oA<6CtDHfpn+f~t#n%5k0A23x<!+nIU?p(T>c(Ac0aAPvQnY>0W*jdJ>3J%RyTPTZf+wi*@6C6+!paSn^'
    '(?12f#))&~EFkB#vWvUFbGGuXKRX-6X%aWXo-'
    '5xKtPs>gj5rkFlkyAmD{jw(is0lS3IPu$a5gHH#NE!WF~$mPH_zWJ?mg^+4v<=*=dJdi>Or-KzaE)n2Q2Q&rJo33t{1k<icMLaur'
    'hM#9kWvK8M$S>teFt}{5SGx`?cN+SMR5)|1~*oybOY9YNDp+H~_u}${kkoM0<~r_cyet6%z|@=2My6fUkL`(k}O4yt9{sU<A1K+#'
    '{{qz3L6MoJrM&`9~dC0`lalEJ`B_?$_HT!I%4_aQn!fx%o_=xfv+!i0zKC=SC(mf%SoJhEv9czX5Co*L>F1J#NE*5)Rp}a69pBjd'
    'Ebn2_s}yk76&G`k>0F>PO)(=KCD<6^~A#KkiUqgVkSZoGy8PY?nxCKsnmchyGfiJoL(ZYVMD`f;>KFqQC1R%66@4CZwxL8Oyb%HQ'
    '9}l?CC|2UYhZO4k*4LT7n5zYlnWRi9;M}%|zL3R`nMb*kJhxNSF>uDY*$_7c+OOQ>VZNntt_AVF-'
    'g<Qh`Clu7F0etN*$^gR9>CvZrRb-{SK}MqPWn=VU!xUkE7u$gf=H1~-H`RHs_6w?Ux()zd8SQfXzgT_J(pRqH2Kul>UDom-mx*3g'
    'oDKt;xxF?*}ELpojUhE!l)uO*LHq)sv}vcqoiYbS7;U7T##gmGCAO$bduB7by3m@)#22u?7w0+<D0)=|@&*%6wa+Z~PCV~(`aUA3'
    'w9P1~oq2oSyYzY~BdGrCa01C974R)Kgd9K*yxA(=Ac-Vzg}D>$(BfDgvN9G77yQck<7i8_5mTT~>6^}7Dd+4gxCSWt>9f;pXRiMm'
    'j#s&#rZ8Gv}VJRUG8h<9l99)cGMTP1rofqdQ`5A@SE2aVo9kCwC|&6WOQDx>E2_b94E1>m%uTH9kTp3rGow@bPf4|Zc$<I^{)JC='
    'ji>kW=QwAEqq9%o{-vV+PFq0u11DM=*)E=9AJB8#6P0(+IE$$*f-'
    'zoJoQlk(^86rGBGj^0^cAb^_<2yty~9rJzdjW;yVIN*Fry#v(gCvd`PcmBK=$TOtmmhYL^WE>6!hN_GC3Fe^uF&tH^-'
    'dYT0Wu_ta=3I;@$H!)iG8OLQgAa@fpZGdqjeB_Iw}oiJ!Wwv)Ch)pePQtb*FRz#z1TMGcVs5)U(l+?2pGDNPsSfUYf}HKiTYz2RS'
    '-`Ab84|Z5T`MW{x+dNYq;~3b8sww>aAbPro;Apw)w;Q79EdxMY!Id)s@QGOAgsY=XpPHXptJ*NGu)wj1db2)#5h=$>cqbWgX+brH'
    'x8b)e{B9L4S43+<?-0usnRVOE&$lUJ`*R~1!B10thNqi<ir)38c56@=vM;T81DI-P<imFje+e~!dM6o{OU-'
    '%5D{Y}m3ZL<qHDBbdHXH!AdpzzcVrE&(@K%K<!U~xODo=DKUz$uW#M4jz4QtgZ71l<+rZ5V2K$w2j>~?oWQbk6ty*UhEYMsYDRp9'
    'gsXprTUo7Hcg%KAW8Ta4+FFAtmpa'
)
_ACTES_SOURCE = json.loads(zlib.decompress(base64.b85decode("".join(_ACTES_SOURCE_B85))))
TYPES_INTERVENTION = tuple(x[0] for x in _ACTES_SOURCE)
POIDS_TYPES_INTERVENTION = tuple(x[1] for x in _ACTES_SOURCE)



def verifier_fichier_source(path: Path, attendu: str) -> dict:
    """Controle l'identite du fichier sans exposer son contenu patient."""
    if not path.exists():
        return {"chemin": str(path), "present": False, "hash_ok": False, "sha256": None}
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return {"chemin": str(path), "present": True, "hash_ok": digest == attendu, "sha256": digest}

JOURS_FR = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]


def barre(valeur: float, maximum: float, largeur: int = 20) -> str:
    """Petite barre de progression texte : [█████░░░░░]. Dépassement -> '!' final."""
    if maximum <= 0:
        return "[" + "░" * largeur + "]"
    ratio = valeur / maximum
    plein = min(largeur, int(round(ratio * largeur)))
    return "[" + "█" * plein + "░" * (largeur - plein) + "]" + ("!" if ratio > 1.0 + 1e-9 else " ")


# ======================================================================
#                            N I V E A U   1
# ======================================================================

DUREE_CRENEAU_MINUTES = 120
TypePlage = Literal["LIBRE", "URGENCE", "INDISPONIBLE"]
GRAINE_ETUDE = 42


@dataclass(frozen=True)
class Chirurgien:
    id: int
    nom: str
    besoin_heures_semaine: float
    salles_autorisees: tuple[int, ...]
    salle_preferee: Optional[int] = None


@dataclass(frozen=True)
class Salle:
    id: int
    nom: str


@dataclass(frozen=True)
class Creneau:
    id: int
    jour: date
    heure_debut: time
    heure_fin: time

    @property
    def duree_minutes(self):
        debut = datetime.combine(self.jour, self.heure_debut)
        fin = datetime.combine(self.jour, self.heure_fin)
        return int((fin - debut).total_seconds() / 60)


@dataclass(frozen=True)
class PlageBloc:
    id: int
    salle_id: int
    creneau_id: int
    type_plage: TypePlage


@dataclass(frozen=True)
class BlocAPlacer:
    id: int
    chirurgien_id: int


@dataclass
class InstanceProbleme:
    chirurgiens: dict[int, Chirurgien]
    salles: dict[int, Salle]
    creneaux: dict[int, Creneau]
    plages_bloc: dict[int, PlageBloc]
    blocs_a_placer: dict[int, BlocAPlacer]
    disponibilites_chirurgiens: dict[int, set[int]] = field(default_factory=dict)
    cache_domaines: dict = field(default_factory=dict, repr=False)


@dataclass
class SolutionPlanning:
    affectations: dict[int, int]

    def copy(self):
        return SolutionPlanning(self.affectations.copy())


@dataclass(frozen=True)
class Vacation:
    id: int
    chirurgien_id: int
    salle_id: int
    jour: date
    heure_debut: time
    heure_fin: time
    creneaux_ids: tuple[int, ...]      # ids de créneaux de la semaine de référence (semaine 0)
    supplementaire: bool = False       # vacation ouverte en plus du planning régulier
    semaine_decalage: int = 0          # 0 = semaine étudiée, 1 = semaine d'après...


@dataclass
class EvaluationPlanning:
    score_total: float
    conflits_salles: int = 0
    conflits_chirurgiens: int = 0
    salles_differentes: int = 0
    fragmentation: int = 0


def creer_blocs_a_placer(chirurgiens):
    blocs = {}
    bloc_id = 1
    for chirurgien in chirurgiens.values():
        nb_blocs = (chirurgien.besoin_heures_semaine * 60) / DUREE_CRENEAU_MINUTES
        if not nb_blocs.is_integer():
            raise ValueError(f"{chirurgien.nom}: besoin horaire incompatible avec des créneaux de 2h")
        for _ in range(int(nb_blocs)):
            blocs[bloc_id] = BlocAPlacer(bloc_id, chirurgien.id)
            bloc_id += 1
    return blocs


def creneaux_se_chevauchent(c1: Creneau, c2: Creneau) -> bool:
    if c1.jour != c2.jour:
        return False
    return c1.heure_debut < c2.heure_fin and c2.heure_debut < c1.heure_fin


def plages_possibles_pour_chirurgien(instance: InstanceProbleme, chirurgien_id: int) -> list[int]:
    """Domaine d'un chirurgien (mis en cache : il ne change jamais pendant la recherche)."""
    if chirurgien_id in instance.cache_domaines:
        return instance.cache_domaines[chirurgien_id][0]
    chirurgien = instance.chirurgiens[chirurgien_id]
    disponibilites = instance.disponibilites_chirurgiens.get(chirurgien_id)
    resultats = []
    for plage_id, plage in instance.plages_bloc.items():
        if plage.type_plage != "LIBRE":
            continue
        if plage.salle_id not in chirurgien.salles_autorisees:
            continue
        if disponibilites is not None and plage.creneau_id not in disponibilites:
            continue
        resultats.append(plage_id)
    instance.cache_domaines[chirurgien_id] = (resultats, frozenset(resultats))
    return resultats


def ensemble_plages_possibles(instance: InstanceProbleme, chirurgien_id: int) -> frozenset:
    plages_possibles_pour_chirurgien(instance, chirurgien_id)
    return instance.cache_domaines[chirurgien_id][1]


def generer_solution_initiale(instance: InstanceProbleme, rng: Optional[random.Random] = None) -> SolutionPlanning:
    """Affectation complète par backtracking (MRV)."""
    tirage = rng if rng is not None else random.Random(GRAINE_ETUDE)
    domaines = {
        bloc_id: list(plages_possibles_pour_chirurgien(instance, bloc.chirurgien_id))
        for bloc_id, bloc in instance.blocs_a_placer.items()
    }
    for domaine in domaines.values():
        tirage.shuffle(domaine)

    affectations = {}
    plages_utilisees = set()

    def compatible(bloc_id, plage_id):
        if plage_id in plages_utilisees:
            return False
        bloc = instance.blocs_a_placer[bloc_id]
        creneau = instance.creneaux[instance.plages_bloc[plage_id].creneau_id]
        for autre_bloc_id, autre_plage_id in affectations.items():
            if instance.blocs_a_placer[autre_bloc_id].chirurgien_id != bloc.chirurgien_id:
                continue
            autre_creneau = instance.creneaux[instance.plages_bloc[autre_plage_id].creneau_id]
            if creneaux_se_chevauchent(creneau, autre_creneau):
                return False
        return True

    def chercher():
        if len(affectations) == len(instance.blocs_a_placer):
            return True
        non_places = [b for b in instance.blocs_a_placer if b not in affectations]
        bloc_id = min(non_places, key=lambda i: sum(compatible(i, p) for p in domaines[i]))
        chirurgien = instance.chirurgiens[instance.blocs_a_placer[bloc_id].chirurgien_id]
        candidats = [p for p in domaines[bloc_id] if compatible(bloc_id, p)]
        candidats.sort(key=lambda p: (chirurgien.salle_preferee is not None
                                      and instance.plages_bloc[p].salle_id != chirurgien.salle_preferee))
        for plage_id in candidats:
            affectations[bloc_id] = plage_id
            plages_utilisees.add(plage_id)
            if chercher():
                return True
            plages_utilisees.remove(plage_id)
            del affectations[bloc_id]
        return False

    if not chercher():
        raise ValueError("Impossible de construire un planning avec les disponibilités et salles fournies.")
    return SolutionPlanning(affectations.copy())


def evaluer_planning(instance: InstanceProbleme, solution: SolutionPlanning) -> EvaluationPlanning:
    """Même fonction objectif que l'original, mais en O(n) / O(n par jour)."""
    conflits_salles = 0
    conflits_chirurgiens = 0
    par_jour: dict[date, list] = {}
    par_chirurgien: dict[int, list] = {}

    for bloc_id, plage_id in solution.affectations.items():
        chir = instance.blocs_a_placer[bloc_id].chirurgien_id
        plage = instance.plages_bloc[plage_id]
        creneau = instance.creneaux[plage.creneau_id]
        par_jour.setdefault(creneau.jour, []).append((chir, plage.salle_id, creneau))
        par_chirurgien.setdefault(chir, []).append((plage.salle_id, creneau))

    for elements in par_jour.values():
        for i in range(len(elements)):
            ch1, s1, c1 = elements[i]
            for j in range(i + 1, len(elements)):
                ch2, s2, c2 = elements[j]
                if not creneaux_se_chevauchent(c1, c2):
                    continue
                if s1 == s2:
                    conflits_salles += 1
                if ch1 == ch2:
                    conflits_chirurgiens += 1

    salles_differentes = 0
    fragmentation = 0
    for elements in par_chirurgien.values():
        salles_differentes += max(0, len({s for s, _ in elements}) - 1)
        groupes: dict = {}
        for salle_id, creneau in elements:
            groupes.setdefault((salle_id, creneau.jour), []).append(creneau)
        nb_groupes = 0
        for liste in groupes.values():
            liste.sort(key=lambda x: x.heure_debut)
            nb_groupes += 1
            for k in range(1, len(liste)):
                if liste[k - 1].heure_fin != liste[k].heure_debut:
                    nb_groupes += 1
        fragmentation += max(0, nb_groupes - 1)

    score = conflits_salles * 10000 + conflits_chirurgiens * 10000 + salles_differentes * 100 + fragmentation * 50
    return EvaluationPlanning(score, conflits_salles, conflits_chirurgiens, salles_differentes, fragmentation)


def generer_voisins_planning(instance: InstanceProbleme, solution: SolutionPlanning,
                             maximum_voisins: int = 500, rng: Optional[random.Random] = None):
    """Voisinage : déplacements (2/3 du budget) + échanges (le reste), tirés au hasard
    (et non plus tronqués sur les premiers blocs). Faisabilité testée localement."""
    tirage = rng if rng is not None else random.Random(GRAINE_ETUDE)
    aff = solution.affectations
    utilisees = set(aff.values())
    blocs_par_chir: dict[int, list[int]] = {}
    for b in aff:
        blocs_par_chir.setdefault(instance.blocs_a_placer[b].chirurgien_id, []).append(b)

    def creneau_de(plage_id):
        return instance.creneaux[instance.plages_bloc[plage_id].creneau_id]

    def libre(chir, creneau, ignores):
        for b in blocs_par_chir[chir]:
            if b in ignores:
                continue
            if creneaux_se_chevauchent(creneau, creneau_de(aff[b])):
                return False
        return True

    voisins = []
    deplacements = []
    for b in aff:
        chir = instance.blocs_a_placer[b].chirurgien_id
        for nouvelle in plages_possibles_pour_chirurgien(instance, chir):
            if nouvelle not in utilisees:
                deplacements.append((b, chir, nouvelle))
    tirage.shuffle(deplacements)
    limite = max(1, 2 * maximum_voisins // 3)
    for b, chir, nouvelle in deplacements:
        if not libre(chir, creneau_de(nouvelle), {b}):
            continue
        voisin = solution.copy()
        voisin.affectations[b] = nouvelle
        voisins.append((voisin, ((b, aff[b], nouvelle),)))
        if len(voisins) >= limite:
            break

    echanges = list(combinations(sorted(aff), 2))
    tirage.shuffle(echanges)
    for b1, b2 in echanges:
        p1, p2 = aff[b1], aff[b2]
        ch1 = instance.blocs_a_placer[b1].chirurgien_id
        ch2 = instance.blocs_a_placer[b2].chirurgien_id
        if p2 not in ensemble_plages_possibles(instance, ch1) or p1 not in ensemble_plages_possibles(instance, ch2):
            continue
        if ch1 != ch2:
            if not libre(ch1, creneau_de(p2), {b1}) or not libre(ch2, creneau_de(p1), {b2}):
                continue
        voisin = solution.copy()
        voisin.affectations[b1] = p2
        voisin.affectations[b2] = p1
        voisins.append((voisin, ((b1, p1, p2), (b2, p2, p1))))
        if len(voisins) >= maximum_voisins:
            break
    return voisins


def construire_vacations(instance: InstanceProbleme, solution: SolutionPlanning) -> dict[int, Vacation]:
    groupes = {}
    for bloc_id, plage_id in solution.affectations.items():
        bloc = instance.blocs_a_placer[bloc_id]
        plage = instance.plages_bloc[plage_id]
        creneau = instance.creneaux[plage.creneau_id]
        groupes.setdefault((bloc.chirurgien_id, plage.salle_id, creneau.jour), []).append(creneau)

    vacations = {}
    vacation_id = 1
    for (chirurgien_id, salle_id, jour), liste in groupes.items():
        liste.sort(key=lambda c: c.heure_debut)
        courant = [liste[0]]
        for creneau in liste[1:]:
            if courant[-1].heure_fin == creneau.heure_debut:
                courant.append(creneau)
            else:
                vacations[vacation_id] = Vacation(vacation_id, chirurgien_id, salle_id, jour,
                                                  courant[0].heure_debut, courant[-1].heure_fin,
                                                  tuple(c.id for c in courant))
                vacation_id += 1
                courant = [creneau]
        vacations[vacation_id] = Vacation(vacation_id, chirurgien_id, salle_id, jour,
                                          courant[0].heure_debut, courant[-1].heure_fin,
                                          tuple(c.id for c in courant))
        vacation_id += 1
    return vacations


def duree_vacation_minutes(vacation: Vacation) -> int:
    debut = datetime.combine(vacation.jour, vacation.heure_debut)
    fin = datetime.combine(vacation.jour, vacation.heure_fin)
    return int((fin - debut).total_seconds() / 60)


# ----------------------------------------------------------------------
# RECHERCHE TABOUE GENERIQUE (utilisée par le Niveau 1)
# ----------------------------------------------------------------------

class RechercheTaboue:
    def __init__(self, evaluer, generer_voisins, iterations=200, taille_tabou=10, patience=50):
        self.evaluer = evaluer
        self.generer_voisins = generer_voisins
        self.iterations = iterations
        self.taille_tabou = taille_tabou
        self.patience = patience

    def optimiser(self, solution_initiale):
        solution = solution_initiale.copy()
        meilleure = solution.copy()
        meilleur_score = self.evaluer(solution)
        liste_taboue = {}
        derniere_amelioration = 0

        for iteration in range(1, self.iterations + 1):
            meilleur_voisin, score_mv, mouvement_mv = None, float("inf"), None
            for voisin, mouvement in self.generer_voisins(solution):
                score = self.evaluer(voisin)
                est_tabou = any(liste_taboue.get((i, nouvelle), 0) >= iteration for i, _, nouvelle in mouvement)
                if est_tabou and score >= meilleur_score:
                    continue
                if score < score_mv:
                    meilleur_voisin, score_mv, mouvement_mv = voisin, score, mouvement
            if meilleur_voisin is None:
                break
            solution = meilleur_voisin
            for identifiant, ancienne, _ in mouvement_mv:
                liste_taboue[(identifiant, ancienne)] = iteration + self.taille_tabou
            if score_mv < meilleur_score:
                meilleure, meilleur_score, derniere_amelioration = meilleur_voisin.copy(), score_mv, iteration
            if iteration - derniere_amelioration >= self.patience:
                break
        return meilleure, meilleur_score


def lancer_tabou(instance, solution_depart, iterations=300, taille_tabou=10, patience=80, graine=GRAINE_ETUDE + 7):
    rng = random.Random(graine)
    tabou = RechercheTaboue(
        evaluer=lambda s: evaluer_planning(instance, s).score_total,
        generer_voisins=lambda s: generer_voisins_planning(instance, s, rng=rng),
        iterations=iterations, taille_tabou=taille_tabou, patience=patience,
    )
    solution_finale, _ = tabou.optimiser(solution_depart)
    return solution_finale, evaluer_planning(instance, solution_finale)


# ----------------------------------------------------------------------
# AFFICHAGE NIVEAU 1
# ----------------------------------------------------------------------

def afficher_planning(instance, solution, evaluation=None, titre="PLANNING"):
    plage_vers_chir = {}
    for bloc_id, plage_id in solution.affectations.items():
        plage_vers_chir[plage_id] = instance.chirurgiens[instance.blocs_a_placer[bloc_id].chirurgien_id].nom

    plage_par_case = {(p.salle_id, p.creneau_id): p for p in instance.plages_bloc.values()}
    jours = sorted({c.jour for c in instance.creneaux.values()})
    creneaux_tries = sorted(instance.creneaux.values(), key=lambda c: (c.jour, c.heure_debut))
    salles_triees = sorted(instance.salles.values(), key=lambda s: s.id)
    largeur = max(12, max(len(s.nom) for s in salles_triees) + 2)

    print("=" * 74)
    print(f"  {titre}")
    print("=" * 74)
    for jour in jours:
        print(f"\n  {JOURS_FR[jour.weekday()]} {jour.strftime('%d/%m/%Y')}")
        print("  " + "─" * 70)
        print("  " + "Horaire".ljust(14) + "".join(s.nom.ljust(largeur) for s in salles_triees))
        for creneau in [c for c in creneaux_tries if c.jour == jour]:
            ligne = "  " + f"{creneau.heure_debut:%H:%M}-{creneau.heure_fin:%H:%M}".ljust(14)
            for salle in salles_triees:
                plage = plage_par_case.get((salle.id, creneau.id))
                if plage is None:
                    contenu = "-"
                elif plage.type_plage == "URGENCE":
                    contenu = "[URGENCE]"
                elif plage.type_plage == "INDISPONIBLE":
                    contenu = "[FERMÉ]"
                else:
                    contenu = plage_vers_chir.get(plage.id, "libre")
                ligne += contenu.ljust(largeur)
            print(ligne)

    vacations = construire_vacations(instance, solution)
    print("\n  VACATIONS RECONSTITUÉES")
    print("  " + "─" * 70)
    for v in sorted(vacations.values(), key=lambda v: (v.jour, v.heure_debut, v.salle_id)):
        print(f"  {instance.chirurgiens[v.chirurgien_id].nom:8s} | {instance.salles[v.salle_id].nom:8s} | "
              f"{v.jour:%d/%m/%Y} | {v.heure_debut:%H:%M} - {v.heure_fin:%H:%M}")

    print("\n  RÉSUMÉ PAR CHIRURGIEN")
    print("  " + "─" * 70)
    for cid, chir in instance.chirurgiens.items():
        vs = [v for v in vacations.values() if v.chirurgien_id == cid]
        salles = sorted({v.salle_id for v in vs})
        heures = sum(duree_vacation_minutes(v) for v in vs) / 60
        print(f"  {chir.nom:8s} | {heures:4.0f} h | {len(vs)} vacation(s) | salle(s) {salles}")

    if evaluation is not None:
        print("\n  SCORE NIVEAU 1 (à minimiser)")
        print("  " + "─" * 70)
        print(f"  Score total            : {evaluation.score_total:.0f}")
        print(f"  Conflits de salle      : {evaluation.conflits_salles}")
        print(f"  Conflits de chirurgien : {evaluation.conflits_chirurgiens}")
        print(f"  Salles différentes     : {evaluation.salles_differentes}  (x100 = {evaluation.salles_differentes*100})")
        print(f"  Fragmentation          : {evaluation.fragmentation}  (x50 = {evaluation.fragmentation*50})")
    print("=" * 74)


def construire_instance_etude() -> InstanceProbleme:
    chirurgiens = {
        1: Chirurgien(1, "Dr A", 14, (1, 2), 1),
        2: Chirurgien(2, "Dr B", 14, (1, 2), 2),
        3: Chirurgien(3, "Dr C", 8, (2, 3), 3),
        4: Chirurgien(4, "Dr D", 8, (1, 3), 3),
        5: Chirurgien(5, "Dr E", 14, (1, 2, 3), None),
        6: Chirurgien(6, "Dr F", 8, (2, 3), 2),
        7: Chirurgien(7, "Dr G", 8, (1,), 1),
        8: Chirurgien(8, "Dr H", 16, (1, 2, 3), None),
    }
    salles = {1: Salle(1, "Salle 1"), 2: Salle(2, "Salle 2"), 3: Salle(3, "Salle 3")}
    jours_semaine = [date(2026, 9, 21), date(2026, 9, 22), date(2026, 9, 23), date(2026, 9, 24), date(2026, 9, 25)]
    horaires = [(time(8), time(10)), (time(10), time(12)), (time(13), time(15)), (time(15), time(17))]

    creneaux, creneau_id, creneaux_par_jour = {}, 1, []
    for jour in jours_semaine:
        ids = []
        for hd, hf in horaires:
            creneaux[creneau_id] = Creneau(creneau_id, jour, hd, hf)
            ids.append(creneau_id)
            creneau_id += 1
        creneaux_par_jour.append(ids)
    lundi, mardi, mercredi, jeudi, vendredi = creneaux_par_jour

    plages_bloc, plage_id = {}, 1
    for salle_id in salles:
        for cid in creneaux:
            urgence = salle_id == 3 and cid in (lundi[0], mardi[0], mercredi[0], jeudi[0], vendredi[0])
            plages_bloc[plage_id] = PlageBloc(plage_id, salle_id, cid, "URGENCE" if urgence else "LIBRE")
            plage_id += 1

    dispo = {
        1: set(lundi + mardi), 2: set(lundi + mardi),
        3: set(mercredi + [mardi[3]]), 4: set(mercredi + [lundi[3]]),
        5: set(jeudi + vendredi), 6: set(jeudi + [vendredi[3]]),
        7: set(vendredi + [jeudi[3]]), 8: set(lundi + mardi + mercredi + jeudi + vendredi),
    }
    return InstanceProbleme(chirurgiens, salles, creneaux, plages_bloc,
                            creer_blocs_a_placer(chirurgiens), dispo)


# Normalisation explicite de la feuille ``Propo CDB a venir`` (semaine paire).
# Les cellules URGENCES/LIBRE, les alternances ambigues et la pause 13h-13h30
# ne sont pas transformees en activite reguliere. La reference de cellule est
# conservee pour rendre l'origine de chaque vacation auditable.
VACATIONS_SOURCE_NORMALISEES = [
    (0, 2, 465, 780, "JT", "F5"), (0, 2, 810, 1050, "JT", "F5"),
    (0, 3, 480, 780, "SR", "I5"), (0, 3, 810, 1050, "SR", "I5"),
    (0, 4, 480, 780, "GA", "M5"), (0, 5, 480, 780, "FN", "Q6"),
    (0, 5, 810, 930, "FN", "Q6/Q9"),
    (1, 2, 465, 780, "JT", "F12"), (1, 2, 810, 930, "JT", "F12"),
    (1, 3, 480, 780, "TR", "I12"), (1, 3, 810, 1050, "MT", "I14"),
    (1, 4, 480, 780, "CT", "M12"), (1, 4, 810, 930, "CT", "M12/M15"),
    (1, 5, 480, 780, "MO", "Q12"), (1, 5, 810, 1050, "MO", "Q12"),
    (2, 2, 465, 780, "CL", "F18"), (2, 2, 810, 1050, "CL", "F18"),
    (2, 3, 480, 780, "DE", "I18"), (2, 3, 810, 1050, "DE", "I18"),
    (2, 5, 480, 780, "MT", "Q18"),
    (3, 2, 465, 780, "DE", "F24"), (3, 2, 810, 1050, "DE", "F24"),
    (3, 3, 480, 780, "SR", "I24"), (3, 3, 810, 930, "SR", "I24/I27"),
    (3, 4, 480, 780, "CT", "M24"), (3, 4, 810, 930, "CT", "M24/M27"),
    (3, 5, 480, 780, "LZ", "Q24"), (3, 5, 810, 1050, "LZ", "Q24"),
    (4, 2, 465, 780, "CL", "F30"), (4, 3, 480, 780, "CU", "I30"),
    (4, 3, 810, 930, "MT", "I32"), (4, 4, 480, 780, "HA", "M30"),
    (4, 4, 810, 1050, "FP", "M32"), (4, 5, 480, 780, "LR", "Q30"),
]


def _minute_vers_heure(minutes: int) -> time:
    return time(minutes // 60, minutes % 60)


def construire_instance_depuis_vacations_source() -> tuple[InstanceProbleme, dict[int, Vacation]]:
    """Construit le niveau 1 a partir des 34 vacations du fichier fourni.

    Les horaires reguliers restent exacts. Les creneaux de deux heures servent
    uniquement a l'ouverture controlee de vacations futures. La disponibilite
    future d'un chirurgien est supposee identique aux jours ou il apparait dans
    la grille source ; cette hypothese est affichee dans le tableau de bord.
    """
    codes = sorted({r[4] for r in VACATIONS_SOURCE_NORMALISEES})
    id_par_code = {code: i + 1 for i, code in enumerate(codes)}
    salles = {sid: Salle(sid, f"Salle {sid}") for sid in (2, 3, 4, 5)}
    base = date(2026, 9, 21)
    horaires = [(time(8), time(10)), (time(10), time(12)),
                (time(13, 30), time(15, 30)), (time(15, 30), time(17, 30))]
    creneaux: dict[int, Creneau] = {}
    ids_par_jour: dict[int, list[int]] = {}
    cid = 1
    for d in range(5):
        ids_par_jour[d] = []
        for hd, hf in horaires:
            creneaux[cid] = Creneau(cid, base + timedelta(days=d), hd, hf)
            ids_par_jour[d].append(cid)
            cid += 1
    plages, plage_id = {}, 1
    for salle_id in salles:
        for creneau_id in creneaux:
            plages[plage_id] = PlageBloc(plage_id, salle_id, creneau_id, "LIBRE")
            plage_id += 1

    minutes_par_chir: dict[str, int] = {code: 0 for code in codes}
    salles_par_chir: dict[str, set[int]] = {code: set() for code in codes}
    minutes_salle_chir: dict[tuple[str, int], int] = {}
    jours_par_chir: dict[str, set[int]] = {code: set() for code in codes}
    vacations: dict[int, Vacation] = {}
    for vid, (d, salle, debut, fin, code, _cellule) in enumerate(VACATIONS_SOURCE_NORMALISEES, 1):
        minutes_par_chir[code] += fin - debut
        salles_par_chir[code].add(salle)
        jours_par_chir[code].add(d)
        minutes_salle_chir[(code, salle)] = minutes_salle_chir.get((code, salle), 0) + fin - debut
        touches = []
        for creneau_id in ids_par_jour[d]:
            c = creneaux[creneau_id]
            a = c.heure_debut.hour * 60 + c.heure_debut.minute
            b = c.heure_fin.hour * 60 + c.heure_fin.minute
            if max(a, debut) < min(b, fin):
                touches.append(creneau_id)
        vacations[vid] = Vacation(
            vid, id_par_code[code], salle, base + timedelta(days=d),
            _minute_vers_heure(debut), _minute_vers_heure(fin), tuple(touches),
        )

    chirurgiens = {}
    disponibilites = {}
    for code in codes:
        autorisees = tuple(sorted(salles_par_chir[code]))
        preferee = max(autorisees, key=lambda s: minutes_salle_chir[(code, s)])
        chirurgiens[id_par_code[code]] = Chirurgien(
            id_par_code[code], code, minutes_par_chir[code] / 60.0,
            autorisees, preferee,
        )
        disponibilites[id_par_code[code]] = {
            creneau_id for d in jours_par_chir[code] for creneau_id in ids_par_jour[d]
        }
    instance = InstanceProbleme(
        chirurgiens, salles, creneaux, plages, {}, disponibilites,
    )
    return instance, vacations


# ======================================================================
#                            N I V E A U   2
# ======================================================================

GRAINE_PATIENTS = GRAINE_ETUDE + 1
MARGE_ALEA_VACATION = 0.10

# Les trois dépassements sont traités comme des contraintes dures par une
# pénalité Big-M. Tant qu'une solution sans dépassement existe, aucune baisse
# des autres coûts ne peut donc compenser une violation de capacité.
POIDS = {
    "non_place": 8000, "lit": 1_000_000, "place": 1_000_000,
    "depassement_vac": 1_000_000,
    # Coût des ressources utilisées et pénalités des violations de capacité.
    # Inoccupation et variance sont des critères secondaires.
    "bloc_inoccupe": 0.05,
    "minute_programmee": 0.08,
    "vacation_supplementaire": 20.0,
    "jour_lit": 1.0,
    "jour_place": 1.0,
    "var_lits": 5.0,
    "var_places": 5.0,
}

# Aucun rang patient d'urgence/priorité n'est présent dans les sources.
# Ces termes sont neutralisés dans le score (poids nuls); leur emplacement réservé
# est uniquement une compatibilité interne avec l'ancien évaluateur.
POIDS_PRIORISATION_ABSENTE = 0.0
POIDS_RETARD_PRIORISATION_ABSENTE = 0.0
# Favorise explicitement une planification courte : coût par jour d’attente et par semaine supplémentaire utilisée.
POIDS_RETARD_PLANNING_PAR_JOUR = 3.0
POIDS_HORIZON_PAR_SEMAINE = 1200.0


@dataclass(frozen=True)
class Patient:
    id: int
    nom: str
    chirurgien_id: int
    ambulatoire: bool
    duree_bloc_minutes: int
    nuits_pre_op: int = 0
    nuits_post_op: int = 0
    type_intervention: str = "Acte non renseigné"
    # Champ historique conservé pour le tri interne, toujours nul faute de priorité source.
    score_priorisation_absente: float = 0.0


@dataclass
class ParametresHebergement:
    lits_disponibles_par_jour: int
    places_ambulatoires_par_jour: int
    reserve_lits: int = 0


@dataclass
class InstanceNiveau2:
    patients: dict[int, Patient]
    vacations: dict[int, Vacation]
    parametres_hebergement: ParametresHebergement
    noms_chirurgiens: dict[int, str] = field(default_factory=dict)


@dataclass
class AffectationPatients:
    affectations: dict[int, Optional[int]]

    def copy(self):
        return AffectationPatients(self.affectations.copy())


@dataclass
class EvaluationAffectation:
    score_total: float
    patients_non_places: int = 0
    violation_capacite_vacation_minutes: float = 0.0
    violation_lits: int = 0
    violation_places: int = 0
    temps_bloc_inoccupe_minutes: float = 0.0
    variance_occupation_lits: float = 0.0
    variance_occupation_places: float = 0.0
    taux_occupation_bloc_pct: float = 0.0
    # --- scores par ressource (leur somme = score_total) ---
    score_blocs: float = 0.0
    score_lits: float = 0.0
    score_places: float = 0.0
    # --- indicateurs d'occupation ---
    taux_occupation_lits_pct: float = 0.0
    pic_lits: int = 0
    taux_occupation_places_pct: float = 0.0
    pic_places: int = 0
    # --- vacations supplémentaires (temps inoccupé non compté dans le coût) ---
    nb_vacations_supp_utilisees: int = 0
    patients_en_supp: int = 0
    minutes_en_supp: float = 0.0
    penalite_priorisation_absente: float = 0.0
    penalite_retard_priorisation_absente: float = 0.0
    penalite_retard_planning: float = 0.0
    penalite_horizon: float = 0.0


def capacite_effective_vacation(vacation: Vacation) -> float:
    return duree_vacation_minutes(vacation) * (1 - MARGE_ALEA_VACATION)


def jours_occupation(patient: Patient, vacation: Vacation) -> list[date]:
    if patient.ambulatoire:
        return [vacation.jour]
    debut = vacation.jour - timedelta(days=patient.nuits_pre_op)
    fin = vacation.jour + timedelta(days=patient.nuits_post_op)
    return [debut + timedelta(days=k) for k in range((fin - debut).days + 1)]


def calculer_occupation_par_jour(instance2, affectation):
    occ_lits: dict[date, int] = {}
    occ_places: dict[date, int] = {}
    for patient_id, vacation_id in affectation.affectations.items():
        if vacation_id is None:
            continue
        patient = instance2.patients[patient_id]
        cible = occ_places if patient.ambulatoire else occ_lits
        for jour in jours_occupation(patient, instance2.vacations[vacation_id]):
            cible[jour] = cible.get(jour, 0) + 1
    return occ_lits, occ_places


def calculer_variance(valeurs: list[float]) -> float:
    if not valeurs:
        return 0.0
    moyenne = sum(valeurs) / len(valeurs)
    return sum((v - moyenne) ** 2 for v in valeurs) / len(valeurs)


def indice_retard_vacation(vacation: Vacation) -> float:
    """Retard relatif : semaine, jour puis début de vacation (plus petit = tôt)."""
    return (vacation.semaine_decalage * 7 + vacation.jour.weekday()
            + (vacation.heure_debut.hour * 60 + vacation.heure_debut.minute) / 1440.0)


def evaluer_affectation(instance2: InstanceNiveau2, affectation: AffectationPatients) -> EvaluationAffectation:
    """Évaluation COMPLÈTE (référence, utilisée pour l'affichage et les vérifications).
    Le score est décomposé en score_blocs + score_lits + score_places."""
    charge_vacation = {v_id: 0.0 for v_id in instance2.vacations}
    non_places = 0
    priorisation_non_place = 0.0
    retard_priorisation = 0.0
    retard_planning = 0.0
    derniere_semaine = 0
    patients_supp = 0
    for patient_id, vacation_id in affectation.affectations.items():
        if vacation_id is None:
            non_places += 1
            priorisation_non_place += instance2.patients[patient_id].score_priorisation_absente
            continue
        vacation_affectee = instance2.vacations[vacation_id]
        retard_priorisation += (
            instance2.patients[patient_id].score_priorisation_absente
            * indice_retard_vacation(vacation_affectee)
        )
        retard_planning += indice_retard_vacation(vacation_affectee)
        derniere_semaine = max(derniere_semaine, vacation_affectee.semaine_decalage)
        charge_vacation[vacation_id] += instance2.patients[patient_id].duree_bloc_minutes
        if instance2.vacations[vacation_id].supplementaire:
            patients_supp += 1

    depassement, inoccupe, utile, capacite_totale = 0.0, 0.0, 0.0, 0.0
    nb_supp, minutes_supp = 0, 0.0
    for vid, vacation in instance2.vacations.items():
        cap, charge = capacite_effective_vacation(vacation), charge_vacation[vid]
        if vacation.supplementaire:
            # vacation optionnelle : seul un dépassement est pénalisé, jamais le temps inoccupé
            if charge > 0:
                nb_supp += 1
                minutes_supp += charge
            if charge > cap:
                depassement += charge - cap
            continue
        capacite_totale += cap
        if charge > cap:
            depassement += charge - cap
            utile += cap
        else:
            inoccupe += cap - charge
            utile += charge
    taux_bloc = utile / capacite_totale * 100 if capacite_totale > 0 else 0.0

    occ_lits, occ_places = calculer_occupation_par_jour(instance2, affectation)
    h = instance2.parametres_hebergement
    cap_lits, cap_places = h.lits_disponibles_par_jour - h.reserve_lits, h.places_ambulatoires_par_jour
    viol_lits = sum(max(0, o - cap_lits) for o in occ_lits.values())
    viol_places = sum(max(0, o - cap_places) for o in occ_places.values())
    var_lits = calculer_variance(list(occ_lits.values()))
    var_places = calculer_variance(list(occ_places.values()))

    minutes_programmees = sum(charge_vacation.values())
    journees_lits = sum(occ_lits.values())
    journees_places = sum(occ_places.values())
    score_blocs = (non_places * POIDS["non_place"]
                   + priorisation_non_place * POIDS_PRIORISATION_ABSENTE
                   + retard_priorisation * POIDS_RETARD_PRIORISATION_ABSENTE
                   + retard_planning * POIDS_RETARD_PLANNING_PAR_JOUR
                   + derniere_semaine * POIDS_HORIZON_PAR_SEMAINE
                   + depassement * POIDS["depassement_vac"]
                   + inoccupe * POIDS["bloc_inoccupe"]
                   + minutes_programmees * POIDS["minute_programmee"]
                   + nb_supp * POIDS["vacation_supplementaire"])
    score_lits = (viol_lits * POIDS["lit"] + var_lits * POIDS["var_lits"]
                  + journees_lits * POIDS["jour_lit"])
    score_places = (viol_places * POIDS["place"] + var_places * POIDS["var_places"]
                    + journees_places * POIDS["jour_place"])

    def taux(occ, cap):
        return (sum(occ.values()) / len(occ) / cap * 100) if occ and cap > 0 else 0.0

    return EvaluationAffectation(
        score_total=score_blocs + score_lits + score_places,
        patients_non_places=non_places,
        violation_capacite_vacation_minutes=depassement,
        violation_lits=viol_lits, violation_places=viol_places,
        temps_bloc_inoccupe_minutes=inoccupe,
        variance_occupation_lits=var_lits, variance_occupation_places=var_places,
        taux_occupation_bloc_pct=taux_bloc,
        score_blocs=score_blocs, score_lits=score_lits, score_places=score_places,
        taux_occupation_lits_pct=taux(occ_lits, cap_lits), pic_lits=max(occ_lits.values(), default=0),
        taux_occupation_places_pct=taux(occ_places, cap_places), pic_places=max(occ_places.values(), default=0),
        nb_vacations_supp_utilisees=nb_supp, patients_en_supp=patients_supp, minutes_en_supp=minutes_supp,
        penalite_priorisation_absente=priorisation_non_place * POIDS_PRIORISATION_ABSENTE,
        penalite_retard_priorisation_absente=retard_priorisation * POIDS_RETARD_PRIORISATION_ABSENTE,
        penalite_retard_planning=retard_planning * POIDS_RETARD_PLANNING_PAR_JOUR,
        penalite_horizon=derniere_semaine * POIDS_HORIZON_PAR_SEMAINE,
    )


def vacations_compatibles(instance2, patient):
    return [v for v in instance2.vacations.values() if v.chirurgien_id == patient.chirurgien_id]


def trier_patients_heuristique(instance2, rng):
    nb_vac: dict[int, int] = {}
    for v in instance2.vacations.values():
        nb_vac[v.chirurgien_id] = nb_vac.get(v.chirurgien_id, 0) + 1
    ids = list(instance2.patients)
    rng.shuffle(ids)
    ids.sort(key=lambda pid: (-instance2.patients[pid].score_priorisation_absente,
                              nb_vac.get(instance2.patients[pid].chirurgien_id, 0),
                              not instance2.patients[pid].ambulatoire,
                              -instance2.patients[pid].duree_bloc_minutes))
    return ids


def construire_affectation_initiale(instance2, rng=None,
                                     durees_dabord: bool = False) -> AffectationPatients:
    """Insertion gloutonne best-fit.

    ``durees_dabord`` ajoute une variante de bin-packing : les opérations les
    plus longues sont rangées en premier afin d'éviter qu'une intervention de
    120–180 minutes reste dehors alors que la capacité totale est suffisante
    mais fragmentée en petits reliquats.
    """
    tirage = rng if rng is not None else random.Random(GRAINE_PATIENTS)
    if durees_dabord:
        nb_vac: dict[int, int] = {}
        for v in instance2.vacations.values():
            nb_vac[v.chirurgien_id] = nb_vac.get(v.chirurgien_id, 0) + 1
        ordre = list(instance2.patients)
        tirage.shuffle(ordre)
        ordre.sort(key=lambda pid: (
            nb_vac.get(instance2.patients[pid].chirurgien_id, 0),
            -instance2.patients[pid].duree_bloc_minutes,
            -instance2.patients[pid].score_priorisation_absente,
            not instance2.patients[pid].ambulatoire,
        ))
    else:
        ordre = trier_patients_heuristique(instance2, tirage)
    affectation = {pid: None for pid in instance2.patients}
    charge = {v: 0.0 for v in instance2.vacations}
    occ_lits: dict[date, int] = {}
    occ_places: dict[date, int] = {}
    h = instance2.parametres_hebergement
    cap_lits, cap_places = h.lits_disponibles_par_jour - h.reserve_lits, h.places_ambulatoires_par_jour

    for pid in ordre:
        patient = instance2.patients[pid]
        meilleure, meilleur_cle = None, None
        for vac in vacations_compatibles(instance2, patient):
            cap = capacite_effective_vacation(vac)
            if charge[vac.id] + patient.duree_bloc_minutes > cap:
                continue
            occ, cmax = (occ_places, cap_places) if patient.ambulatoire else (occ_lits, cap_lits)
            if any(occ.get(j, 0) + 1 > cmax for j in jours_occupation(patient, vac)):
                continue
            reste = cap - (charge[vac.id] + patient.duree_bloc_minutes)
            # vacations régulières d'abord, puis supplémentaires (semaine la plus proche), puis best-fit
            cle = (vac.supplementaire, indice_retard_vacation(vac), reste)
            if meilleur_cle is None or cle < meilleur_cle:
                meilleur_cle, meilleure = cle, vac
        if meilleure is None:
            continue
        affectation[pid] = meilleure.id
        charge[meilleure.id] += patient.duree_bloc_minutes
        occ = occ_places if patient.ambulatoire else occ_lits
        for j in jours_occupation(patient, meilleure):
            occ[j] = occ.get(j, 0) + 1
    return AffectationPatients(affectation)


def construire_meilleure_affectation_initiale(instance2, nb_essais: int = 40,
                                               graine: int = GRAINE_PATIENTS):
    """Multi-départ : plusieurs constructions gloutonnes (départages aléatoires
    différents), on garde la meilleure."""
    meilleure, meilleur_score = None, float("inf")
    for k in range(nb_essais):
        cand = construire_affectation_initiale(
            instance2, random.Random(graine + k), durees_dabord=(k % 3 != 0),
        )
        s = evaluer_affectation(instance2, cand).score_total
        if s < meilleur_score:
            meilleure, meilleur_score = cand, s
    return meilleure


# ----------------------------------------------------------------------
# EVALUATION INCREMENTALE NIVEAU 2
# ----------------------------------------------------------------------

class SuiviOccupation:
    """Occupation jour par jour d'une ressource (lits OU places), avec
    violation de capacité et statistiques de variance tenues à jour en O(1)
    par jour modifié. La variance porte, comme dans l'étude, sur les jours
    où l'occupation est > 0."""
    __slots__ = ("cap", "occ", "violation", "n", "s1", "s2")

    def __init__(self, cap):
        self.cap, self.occ = cap, {}
        self.violation, self.n, self.s1, self.s2 = 0, 0, 0, 0

    def modifier(self, jours, delta):
        occ, cap = self.occ, self.cap
        for j in jours:
            o = occ.get(j, 0)
            no = o + delta
            if o > cap:
                self.violation -= o - cap
            if no > cap:
                self.violation += no - cap
            if o > 0:
                self.n -= 1
                self.s1 -= o
                self.s2 -= o * o
            if no > 0:
                self.n += 1
                self.s1 += no
                self.s2 += no * no
                occ[j] = no
            else:
                occ.pop(j, None)

    def variance(self):
        if self.n == 0:
            return 0.0
        m = self.s1 / self.n
        return max(0.0, self.s2 / self.n - m * m)


class EtatNiveau2:
    """Solution modifiable en place : deplacer(patient, vacation) met à jour
    charges, occupations et scores sans rien recalculer depuis zéro."""

    def __init__(self, instance2, affectation: dict):
        self.patients = instance2.patients
        h = instance2.parametres_hebergement
        self.lits = SuiviOccupation(h.lits_disponibles_par_jour - h.reserve_lits)
        self.places = SuiviOccupation(h.places_ambulatoires_par_jour)
        self.vacations = instance2.vacations
        self.cap = {vid: capacite_effective_vacation(v) for vid, v in instance2.vacations.items()}
        self.charge = {vid: 0.0 for vid in instance2.vacations}
        self.depassement = 0.0
        self.supp = {vid for vid, v in instance2.vacations.items() if v.supplementaire}
        self.minutes_placees = 0.0
        self.nb_supp_utilisees = 0
        self.inoccupe = sum(c for vid, c in self.cap.items() if vid not in self.supp)
        self.non_places = len(instance2.patients)
        self.priorisation_non_place = sum(p.score_priorisation_absente for p in instance2.patients.values())
        self.retard_priorisation = 0.0
        self.retard_planning = 0.0
        self.occupes_par_semaine: dict[int, int] = {}
        self.aff = {pid: None for pid in instance2.patients}
        self._jours: dict = {}
        for pid, vid in affectation.items():
            if vid is not None:
                self.deplacer(pid, vid)

    def _jours_de(self, pid, vid):
        cle = (pid, vid)
        j = self._jours.get(cle)
        if j is None:
            j = self._jours[cle] = tuple(jours_occupation(self.patients[pid], self.vacations[vid]))
        return j

    def _charge(self, vid, delta):
        cap, ancien = self.cap[vid], self.charge[vid]
        nouveau = ancien + delta
        self.minutes_placees += delta
        if vid in self.supp:
            if ancien <= 0 < nouveau:
                self.nb_supp_utilisees += 1
            elif ancien > 0 >= nouveau:
                self.nb_supp_utilisees -= 1
        regulier = vid not in self.supp     # le temps inoccupé des vacations supp. n'est pas compté
        if ancien > cap:
            self.depassement -= ancien - cap
        elif regulier:
            self.inoccupe -= cap - ancien
        if nouveau > cap:
            self.depassement += nouveau - cap
        elif regulier:
            self.inoccupe += cap - nouveau
        self.charge[vid] = nouveau

    def deplacer(self, pid, nouvelle):
        ancienne = self.aff[pid]
        if ancienne == nouvelle:
            return
        p = self.patients[pid]
        res = self.places if p.ambulatoire else self.lits
        if ancienne is None:
            self.non_places -= 1
            self.priorisation_non_place -= p.score_priorisation_absente
        else:
            self._charge(ancienne, -p.duree_bloc_minutes)
            res.modifier(self._jours_de(pid, ancienne), -1)
            ancienne_vac = self.vacations[ancienne]
            self.retard_priorisation -= p.score_priorisation_absente * indice_retard_vacation(ancienne_vac)
            self.retard_planning -= indice_retard_vacation(ancienne_vac)
            semaine = ancienne_vac.semaine_decalage
            self.occupes_par_semaine[semaine] -= 1
            if self.occupes_par_semaine[semaine] == 0:
                del self.occupes_par_semaine[semaine]
        if nouvelle is None:
            self.non_places += 1
            self.priorisation_non_place += p.score_priorisation_absente
        else:
            self._charge(nouvelle, p.duree_bloc_minutes)
            res.modifier(self._jours_de(pid, nouvelle), +1)
            nouvelle_vac = self.vacations[nouvelle]
            self.retard_priorisation += p.score_priorisation_absente * indice_retard_vacation(nouvelle_vac)
            self.retard_planning += indice_retard_vacation(nouvelle_vac)
            semaine = nouvelle_vac.semaine_decalage
            self.occupes_par_semaine[semaine] = self.occupes_par_semaine.get(semaine, 0) + 1
        self.aff[pid] = nouvelle

    def score_blocs(self):
        return (self.non_places * POIDS["non_place"]
                + self.priorisation_non_place * POIDS_PRIORISATION_ABSENTE
                + self.retard_priorisation * POIDS_RETARD_PRIORISATION_ABSENTE
                + self.retard_planning * POIDS_RETARD_PLANNING_PAR_JOUR
                + max(self.occupes_par_semaine, default=0) * POIDS_HORIZON_PAR_SEMAINE
                + self.depassement * POIDS["depassement_vac"]
                + self.inoccupe * POIDS["bloc_inoccupe"]
                + self.minutes_placees * POIDS["minute_programmee"]
                + self.nb_supp_utilisees * POIDS["vacation_supplementaire"])

    def score_lits(self):
        return (self.lits.violation * POIDS["lit"]
                + self.lits.variance() * POIDS["var_lits"]
                + self.lits.s1 * POIDS["jour_lit"])

    def score_places(self):
        return (self.places.violation * POIDS["place"]
                + self.places.variance() * POIDS["var_places"]
                + self.places.s1 * POIDS["jour_place"])

    def score(self):
        return self.score_blocs() + self.score_lits() + self.score_places()


def lancer_tabou_niveau2(instance2: InstanceNiveau2, affectation_depart: AffectationPatients,
                         iterations: int = 5000, taille_tabou: int = 15,
                         temps_max_secondes: float = 40.0, patience: int = 100,
                         nb_echanges_par_iteration: int = 500, graine: int = GRAINE_PATIENTS,
                         verbose: bool = True):
    """Recherche taboue Niveau 2 (évaluation incrémentale, perturbation si stagnation)."""
    EPS = 1e-9
    rng = random.Random(graine)
    etat = EtatNiveau2(instance2, affectation_depart.affectations)
    meilleur_score = etat.score()
    meilleure = dict(etat.aff)

    pids = sorted(instance2.patients)
    vac_compat = {pid: [v.id for v in vacations_compatibles(instance2, instance2.patients[pid])] for pid in pids}
    par_chir: dict[int, list[int]] = {}
    for pid in pids:
        par_chir.setdefault(instance2.patients[pid].chirurgien_id, []).append(pid)
    paires = [pr for lst in par_chir.values() for pr in combinations(lst, 2)]

    tabou: dict = {}
    t0 = chrono.perf_counter()
    derniere_amelioration = 0
    nb_perturbations = 0
    it = 0

    for it in range(1, iterations + 1):
        if chrono.perf_counter() - t0 > temps_max_secondes:
            break
        best_s, best_mv, nb_egaux = float("inf"), None, 0

        # --- déplacements (voisinage complet) ---
        for pid in pids:
            if chrono.perf_counter() - t0 > temps_max_secondes:
                break
            ancienne = etat.aff[pid]
            for w in vac_compat[pid]:
                if w == ancienne:
                    continue
                etat.deplacer(pid, w)
                s = etat.score()
                etat.deplacer(pid, ancienne)
                if tabou.get((pid, w), 0) >= it and s >= meilleur_score - EPS:
                    continue
                if s < best_s - EPS:
                    best_s, best_mv, nb_egaux = s, ((pid, ancienne, w),), 1
                elif abs(s - best_s) <= EPS:
                    nb_egaux += 1
                    if rng.random() < 1.0 / nb_egaux:
                        best_mv = ((pid, ancienne, w),)

        # --- échanges (échantillon) ---
        temps_epuise = chrono.perf_counter() - t0 > temps_max_secondes
        echantillon = [] if temps_epuise else (
            paires if len(paires) <= nb_echanges_par_iteration
            else rng.sample(paires, nb_echanges_par_iteration)
        )
        for a, b in echantillon:
            if chrono.perf_counter() - t0 > temps_max_secondes:
                break
            v1, v2 = etat.aff[a], etat.aff[b]
            if v1 == v2:
                continue
            etat.deplacer(a, v2)
            etat.deplacer(b, v1)
            s = etat.score()
            etat.deplacer(b, v2)
            etat.deplacer(a, v1)
            if (tabou.get((a, v2), 0) >= it or tabou.get((b, v1), 0) >= it) and s >= meilleur_score - EPS:
                continue
            if s < best_s - EPS:
                best_s, best_mv, nb_egaux = s, ((a, v1, v2), (b, v2, v1)), 1
            elif abs(s - best_s) <= EPS:
                nb_egaux += 1
                if rng.random() < 1.0 / nb_egaux:
                    best_mv = ((a, v1, v2), (b, v2, v1))

        if best_mv is None:
            if chrono.perf_counter() - t0 > temps_max_secondes:
                break
            tabou.clear()
            continue

        for pid, ancienne, nouvelle in best_mv:
            etat.deplacer(pid, nouvelle)
            if ancienne is not None:
                tabou[(pid, ancienne)] = it + taille_tabou + rng.randint(0, 5)

        if best_s < meilleur_score - EPS:
            meilleur_score, meilleure, derniere_amelioration = best_s, dict(etat.aff), it
            if verbose:
                print(f"    it {it:5d} | {chrono.perf_counter() - t0:5.1f}s | meilleur score = {meilleur_score:,.0f}")

        # --- perturbation en cas de stagnation : on repart du meilleur ---
        if it - derniere_amelioration >= patience:
            etat = EtatNiveau2(instance2, meilleure)
            for _ in range(rng.randint(3, 8)):
                pid = rng.choice(pids)
                if vac_compat[pid]:
                    etat.deplacer(pid, rng.choice(vac_compat[pid]))
            tabou.clear()
            derniere_amelioration = it
            nb_perturbations += 1

    if verbose:
        print(f"    -> {it} itérations, {nb_perturbations} perturbation(s), {chrono.perf_counter() - t0:.1f}s")
    finale = AffectationPatients(meilleure)
    return finale, evaluer_affectation(instance2, finale)


# ----------------------------------------------------------------------
# VACATIONS SUPPLEMENTAIRES
# ----------------------------------------------------------------------

def calculer_besoins_supplementaires(instance2, affectation: AffectationPatients, marge: float = 1.10):
    """Pour chaque chirurgien : minutes à absorber (patients non placés + dépassements
    de ses vacations) et indicateur « besoin long » (un patient non placé est plus
    long que toute vacation du chirurgien -> il faut une vacation de 4h)."""
    charge = {vid: 0.0 for vid in instance2.vacations}
    for pid, vid in affectation.affectations.items():
        if vid is not None:
            charge[vid] += instance2.patients[pid].duree_bloc_minutes

    minutes: dict[int, float] = {}
    cap_max: dict[int, float] = {}
    for vid, v in instance2.vacations.items():
        cap = capacite_effective_vacation(v)
        cap_max[v.chirurgien_id] = max(cap_max.get(v.chirurgien_id, 0.0), cap)
        if charge[vid] > cap:
            minutes[v.chirurgien_id] = minutes.get(v.chirurgien_id, 0.0) + charge[vid] - cap

    longs: dict[int, bool] = {}
    for pid, vid in affectation.affectations.items():
        if vid is None:
            p = instance2.patients[pid]
            minutes[p.chirurgien_id] = minutes.get(p.chirurgien_id, 0.0) + p.duree_bloc_minutes
            if p.duree_bloc_minutes > cap_max.get(p.chirurgien_id, 0.0):
                longs[p.chirurgien_id] = True
    return {c: (m * marge, longs.get(c, False)) for c, m in minutes.items() if m > 0}


def generer_vacations_supplementaires(instance1: InstanceProbleme, vacations: dict[int, Vacation],
                                      besoins: dict, semaines_extra: int = 1,
                                      planning_repete: bool = True) -> dict[int, Vacation]:
    """Ouvre de nouvelles vacations dans les plages LIBRES, cette semaine (k=0) puis
    la semaine suivante (k=1...), dans le respect des salles autorisées, des
    disponibilités du chirurgien et de ses autres vacations (pas de double réservation).

    - planning_repete=True : le planning régulier de la semaine étudiée est supposé
      reconduit à l'identique les semaines suivantes (donc seules les plages libres
      servent). False : les semaines suivantes sont entièrement libres.
    - Un besoin « long » déclenche en priorité une vacation de 4h (2 créneaux contigus)."""
    plage_type = {(p.salle_id, p.creneau_id): p.type_plage for p in instance1.plages_bloc.values()}
    jours = sorted({c.jour for c in instance1.creneaux.values()})
    par_jour = {j: sorted((c for c in instance1.creneaux.values() if c.jour == j), key=lambda c: c.heure_debut)
                for j in jours}

    occupees: set = set()   # (semaine, salle, creneau)
    occupe_chir: set = set()  # (semaine, chirurgien, creneau)
    for v in vacations.values():
        semaines = range(semaines_extra + 1) if (planning_repete and not v.supplementaire) else [v.semaine_decalage]
        for k in semaines:
            for cid in v.creneaux_ids:
                occupees.add((k, v.salle_id, cid))
                occupe_chir.add((k, v.chirurgien_id, cid))

    restant = {c: m for c, (m, _) in besoins.items() if m > 0}
    besoin_long = {c: l for c, (_, l) in besoins.items()}
    cap_simple = DUREE_CRENEAU_MINUTES * (1 - MARGE_ALEA_VACATION)

    def meilleur_groupe(chir_id, k):
        chir = instance1.chirurgiens[chir_id]
        dispo = instance1.disponibilites_chirurgiens.get(chir_id)
        salles = sorted(chir.salles_autorisees, key=lambda s: (s != chir.salle_preferee, s))
        candidats = []
        for jour in jours:
            for rang, salle_id in enumerate(salles):
                libres = [c for c in par_jour[jour]
                          # En semaine 0, seules les plages explicitement LIBRES
                          # peuvent devenir des vacations supplementaires. Quand
                          # ``planning_repete`` vaut False, les semaines futures
                          # representent un nouvel horizon a construire : les
                          # plages regulieres de la semaine-type redeviennent donc
                          # disponibles, seules les indisponibilites restant
                          # interdites. L'ancienne condition LIBRE appliquee a
                          # toutes les semaines contredisait ce modele et bloquait
                          # artificiellement le chirurgien le plus charge.
                          if (((k == 0 or planning_repete)
                               and plage_type.get((salle_id, c.id)) == "LIBRE")
                              or ((k > 0 and not planning_repete)
                                  and plage_type.get((salle_id, c.id)) != "INDISPONIBLE"))
                          and (dispo is None or c.id in dispo)
                          and (k, salle_id, c.id) not in occupees
                          and (k, chir_id, c.id) not in occupe_chir]
                series, cur = [], []
                for c in libres:
                    if cur and cur[-1].heure_fin == c.heure_debut:
                        cur.append(c)
                    else:
                        if cur:
                            series.append(cur)
                        cur = [c]
                if cur:
                    series.append(cur)
                for serie in series:
                    if len(serie) >= 2:
                        candidats.append((jour, serie[0].heure_debut, rang, serie[:2], salle_id))
                    candidats.append((jour, serie[0].heure_debut, rang, serie[:1], salle_id))
        if not candidats:
            return None
        veut_paire = besoin_long.get(chir_id, False) or restant[chir_id] > cap_simple
        pool = [c for c in candidats if (len(c[3]) == 2) == veut_paire] or candidats
        return min(pool, key=lambda c: c[:3])

    nouvelles: dict[int, Vacation] = {}
    prochain_id = max(vacations, default=0) + 1
    for k in range(semaines_extra + 1):
        progres = True
        while progres and any(r > 0 for r in restant.values()):
            progres = False
            for chir_id in sorted(restant, key=lambda c: -restant[c]):   # un groupe par chirurgien et par passe
                if restant[chir_id] <= 0:
                    continue
                choix = meilleur_groupe(chir_id, k)
                if choix is None:
                    continue
                jour, _, _, groupe, salle_id = choix
                nouvelles[prochain_id] = Vacation(
                    prochain_id, chir_id, salle_id, jour + timedelta(days=7 * k),
                    groupe[0].heure_debut, groupe[-1].heure_fin, tuple(c.id for c in groupe),
                    supplementaire=True, semaine_decalage=k)
                prochain_id += 1
                for c in groupe:
                    occupees.add((k, salle_id, c.id))
                    occupe_chir.add((k, chir_id, c.id))
                restant[chir_id] -= sum(c.duree_minutes for c in groupe) * (1 - MARGE_ALEA_VACATION)
                if len(groupe) == 2:
                    besoin_long[chir_id] = False
                progres = True
    return nouvelles


def optimiser_avec_vacations_supplementaires(instance1, instance2, affectation, max_tours: int = 3,
                                             semaines_extra: int = 1, planning_repete: bool = True,
                                             temps_par_tour: float = 15.0, verbose: bool = True,
                                             graine: int = GRAINE_PATIENTS):
    """Boucle : besoins -> ouverture de vacations supplémentaires -> nouvelle recherche
    taboue (départ à chaud). Les vacations supplémentaires restées vides sont retirées."""
    evaluation = evaluer_affectation(instance2, affectation)
    for tour in range(1, max_tours + 1):
        besoins = calculer_besoins_supplementaires(instance2, affectation)
        if not besoins:
            break
        nouvelles = generer_vacations_supplementaires(instance1, instance2.vacations, besoins,
                                                      semaines_extra, planning_repete)
        if not nouvelles:
            if verbose:
                print(f"    tour {tour} : plus aucune plage libre exploitable.")
            break
        instance2.vacations.update(nouvelles)
        # Essai d'insertion directe dans la capacité qui vient d'être créée.
        # Sans cette étape, le voisinage peut ne jamais visiter la nouvelle
        # vacation et celle-ci serait ensuite supprimée comme « inutilisée ».
        etat_insertion = EtatNiveau2(instance2, affectation.affectations)
        non_places_ordonnes = sorted(
            (pid for pid, vid in etat_insertion.aff.items() if vid is None),
            key=lambda pid: (-instance2.patients[pid].score_priorisation_absente,
                             -instance2.patients[pid].duree_bloc_minutes),
        )
        for pid in non_places_ordonnes:
            p = instance2.patients[pid]
            ressource = etat_insertion.places if p.ambulatoire else etat_insertion.lits
            options = []
            for v in vacations_compatibles(instance2, p):
                if etat_insertion.charge[v.id] + p.duree_bloc_minutes > etat_insertion.cap[v.id]:
                    continue
                jours = etat_insertion._jours_de(pid, v.id)
                if any(ressource.occ.get(j, 0) + 1 > ressource.cap for j in jours):
                    continue
                reste = etat_insertion.cap[v.id] - etat_insertion.charge[v.id] - p.duree_bloc_minutes
                options.append((v.id not in nouvelles, reste, indice_retard_vacation(v), v.id))
            if options:
                etat_insertion.deplacer(pid, min(options)[3])
        insertion = AffectationPatients(dict(etat_insertion.aff))
        evaluation_insertion = evaluer_affectation(instance2, insertion)
        # Le voisinage local peut conserver artificiellement un patient hors
        # planning après l'ouverture de nouvelles vacations. On reconstruit
        # donc aussi plusieurs solutions faisables depuis zéro et l'on garde
        # le meilleur point de départ selon l'ordre : contraintes, placement,
        # puis score. Cela évite qu'une solution à 99/100 reste bloquée alors
        # qu'une réinsertion globale à 100/100 existe.
        redepart = construire_meilleure_affectation_initiale(
            instance2, nb_essais=24, graine=graine + tour * 7919,
        )
        evaluation_redepart = evaluer_affectation(instance2, redepart)
        cle = lambda ev: (
            ev.violation_capacite_vacation_minutes + ev.violation_lits + ev.violation_places,
            ev.patients_non_places,
            ev.score_total,
        )
        evaluation_courante = evaluer_affectation(instance2, affectation)
        affectation, evaluation = min(
            ((affectation, evaluation_courante),
             (insertion, evaluation_insertion),
             (redepart, evaluation_redepart)),
            key=lambda paire: cle(paire[1]),
        )
        # Cette phase ajoute/répare des vacations pour obtenir un individu
        # faisable; elle prépare les contraintes avant la recherche taboue finale.
        evaluation = evaluer_affectation(instance2, affectation)
        faisable = (
            evaluation.patients_non_places == 0
            and evaluation.violation_capacite_vacation_minutes <= 1e-9
            and evaluation.violation_lits == 0
            and evaluation.violation_places == 0
        )
        if not faisable:
            # En cours de construction, on libère les capacités inutilisées.
            # Dès qu'un planning complet existe, on garde les autres vacations
            # candidates pour pouvoir tester un horizon hebdomadaire plus court.
            utilisees = {v for v in affectation.affectations.values() if v is not None}
            for vid in [vid for vid, v in instance2.vacations.items()
                        if v.supplementaire and vid not in utilisees]:
                del instance2.vacations[vid]
            evaluation = evaluer_affectation(instance2, affectation)
        if verbose:
            print(f"    tour {tour} : +{len(nouvelles)} vacation(s) ouvertes, "
                  f"{evaluation.nb_vacations_supp_utilisees} utilisée(s), "
                  f"{evaluation.patients_non_places} non placé(s), score = {evaluation.score_total:,.0f}")
        if faisable:
            break
    return affectation, evaluation


def reparer_non_places_par_chirurgien(instance2: InstanceNiveau2,
                                      affectation: AffectationPatients,
                                      graine: int,
                                      temps_max_secondes: float = 8.0) -> tuple[AffectationPatients, EvaluationAffectation]:
    """Répare localement la fragmentation des vacations d'un chirurgien.

    Les affectations des autres chirurgiens restent fixes. Pour chaque
    chirurgien ayant au moins un patient non placé, plusieurs rangements
    best-fit aléatoires sont testés sur l'ensemble de ses patients et de ses
    vacations, avec contrôle immédiat des blocs, lits et places.
    """
    meilleure = AffectationPatients(dict(affectation.affectations))
    meilleure_eval = evaluer_affectation(instance2, meilleure)
    if meilleure_eval.patients_non_places == 0:
        return meilleure, meilleure_eval

    rng = random.Random(graine)
    debut = chrono.perf_counter()
    chirurgiens_a_reparer = sorted({
        instance2.patients[pid].chirurgien_id
        for pid, vid in meilleure.affectations.items() if vid is None
    })
    h = instance2.parametres_hebergement
    cap_lits = h.lits_disponibles_par_jour - h.reserve_lits
    cap_places = h.places_ambulatoires_par_jour

    for chir_id in chirurgiens_a_reparer:
        pids = [pid for pid, p in instance2.patients.items() if p.chirurgien_id == chir_id]
        vids = [v.id for v in instance2.vacations.values() if v.chirurgien_id == chir_id]
        base = dict(meilleure.affectations)
        for pid in pids:
            base[pid] = None
        occ_lits_base, occ_places_base = calculer_occupation_par_jour(
            instance2, AffectationPatients(base),
        )

        # Recherche exacte ciblée (MRV + backtracking) : elle ne porte que sur
        # les patients et vacations du chirurgien bloqué. Le reste du planning
        # est gelé dans les occupations de base.
        capacites_restantes = {vid: capacite_effective_vacation(instance2.vacations[vid]) for vid in vids}
        occ_lits_exact, occ_places_exact = dict(occ_lits_base), dict(occ_places_base)
        jours_cache = {(pid, vid): tuple(jours_occupation(instance2.patients[pid], instance2.vacations[vid]))
                       for pid in pids for vid in vids}
        affectation_locale: dict[int, int] = {}
        limite_exacte = debut + temps_max_secondes * 0.75
        noeuds = 0

        def options_faisables(pid: int):
            p = instance2.patients[pid]
            occ = occ_places_exact if p.ambulatoire else occ_lits_exact
            cmax = cap_places if p.ambulatoire else cap_lits
            options = []
            for vid in vids:
                if capacites_restantes[vid] < p.duree_bloc_minutes:
                    continue
                jours = jours_cache[(pid, vid)]
                if any(occ.get(j, 0) + 1 > cmax for j in jours):
                    continue
                v = instance2.vacations[vid]
                options.append((capacites_restantes[vid] - p.duree_bloc_minutes,
                                indice_retard_vacation(v), vid))
            return options

        def placer_exactement(restants: tuple[int, ...]) -> bool:
            nonlocal noeuds
            noeuds += 1
            if chrono.perf_counter() > limite_exacte:
                return False
            if not restants:
                return True
            # Minimum Remaining Values : on traite le patient ayant le moins
            # de vacations encore faisables, puis le plus long.
            choix_pid, choix_options = None, None
            for pid in restants:
                opts = options_faisables(pid)
                if not opts:
                    return False
                if (choix_options is None or len(opts) < len(choix_options)
                        or (len(opts) == len(choix_options)
                            and instance2.patients[pid].duree_bloc_minutes
                            > instance2.patients[choix_pid].duree_bloc_minutes)):
                    choix_pid, choix_options = pid, opts
            p = instance2.patients[choix_pid]
            # Best-fit pour limiter la fragmentation ; à égalité, les urgences
            # utilisent les vacations les plus proches.
            choix_options.sort(key=lambda x: (x[0], x[1] if p.score_priorisation_absente > 0 else 0))
            suivants = tuple(pid for pid in restants if pid != choix_pid)
            for _, _, vid in choix_options:
                capacites_restantes[vid] -= p.duree_bloc_minutes
                occ = occ_places_exact if p.ambulatoire else occ_lits_exact
                jours = jours_cache[(choix_pid, vid)]
                for jour in jours:
                    occ[jour] = occ.get(jour, 0) + 1
                affectation_locale[choix_pid] = vid
                if placer_exactement(suivants):
                    return True
                affectation_locale.pop(choix_pid, None)
                for jour in jours:
                    occ[jour] -= 1
                    if occ[jour] == 0:
                        del occ[jour]
                capacites_restantes[vid] += p.duree_bloc_minutes
            return False

        ordre_exact = tuple(sorted(
            pids,
            key=lambda pid: (-instance2.patients[pid].duree_bloc_minutes,
                             -instance2.patients[pid].score_priorisation_absente),
        ))
        if placer_exactement(ordre_exact):
            candidat_exact = dict(base)
            candidat_exact.update(affectation_locale)
            evaluation_exacte = evaluer_affectation(instance2, AffectationPatients(candidat_exact))
            if (evaluation_exacte.violation_capacite_vacation_minutes == 0
                    and evaluation_exacte.violation_lits == 0
                    and evaluation_exacte.violation_places == 0
                    and evaluation_exacte.patients_non_places == 0):
                meilleure, meilleure_eval = AffectationPatients(candidat_exact), evaluation_exacte
                continue

        essais = 0
        while essais < 5000 and chrono.perf_counter() - debut < temps_max_secondes:
            essais += 1
            ordre = list(pids)
            rng.shuffle(ordre)
            mode = essais % 4
            if mode == 0:
                ordre.sort(key=lambda pid: (-instance2.patients[pid].duree_bloc_minutes,
                                             -instance2.patients[pid].score_priorisation_absente))
            elif mode == 1:
                ordre.sort(key=lambda pid: (instance2.patients[pid].ambulatoire,
                                             -len(jours_occupation(instance2.patients[pid], instance2.vacations[vids[0]])),
                                             -instance2.patients[pid].duree_bloc_minutes))
            elif mode == 2:
                ordre.sort(key=lambda pid: (-instance2.patients[pid].score_priorisation_absente,
                                             -instance2.patients[pid].duree_bloc_minutes))
            else:
                ordre.sort(key=lambda pid: (-instance2.patients[pid].duree_bloc_minutes,
                                             instance2.patients[pid].ambulatoire))

            charge = {vid: 0.0 for vid in vids}
            occ_lits, occ_places = dict(occ_lits_base), dict(occ_places_base)
            candidat = dict(base)
            echec = False
            for pid in ordre:
                p = instance2.patients[pid]
                options = []
                for vid in vids:
                    v = instance2.vacations[vid]
                    cap = capacite_effective_vacation(v)
                    if charge[vid] + p.duree_bloc_minutes > cap:
                        continue
                    occ = occ_places if p.ambulatoire else occ_lits
                    cmax = cap_places if p.ambulatoire else cap_lits
                    jours = jours_occupation(p, v)
                    if any(occ.get(j, 0) + 1 > cmax for j in jours):
                        continue
                    options.append((cap - charge[vid] - p.duree_bloc_minutes,
                                    indice_retard_vacation(v), vid, jours))
                if not options:
                    echec = True
                    break
                options.sort(key=lambda x: (x[0], x[1]))
                # Un peu de diversification parmi les meilleurs best-fit.
                choix = options[0] if essais % 5 else rng.choice(options[:min(3, len(options))])
                _, _, vid, jours = choix
                candidat[pid] = vid
                charge[vid] += p.duree_bloc_minutes
                occ = occ_places if p.ambulatoire else occ_lits
                for jour in jours:
                    occ[jour] = occ.get(jour, 0) + 1
            if echec:
                continue
            evaluation = evaluer_affectation(instance2, AffectationPatients(candidat))
            cle = lambda ev: (
                ev.violation_capacite_vacation_minutes + ev.violation_lits + ev.violation_places,
                ev.patients_non_places,
                ev.score_total,
            )
            if cle(evaluation) < cle(meilleure_eval):
                meilleure, meilleure_eval = AffectationPatients(candidat), evaluation
                if (meilleure_eval.patients_non_places == 0
                        and meilleure_eval.violation_capacite_vacation_minutes == 0
                        and meilleure_eval.violation_lits == 0
                        and meilleure_eval.violation_places == 0):
                    break

    return meilleure, meilleure_eval


def garantir_placement_restant(instance1: InstanceProbleme,
                               instance2: InstanceNiveau2,
                               affectation: AffectationPatients,
                               horizon_semaines: int = 20
                               ) -> tuple[AffectationPatients, EvaluationAffectation]:
    """Place deterministement les derniers patients sur le premier creneau faisable.

    Cette phase n'est utilisee qu'apres les heuristiques de minimisation. Elle
    garantit qu'un echec de voisinage ne laisse pas artificiellement un patient
    hors planning alors qu'une semaine future peut etre ouverte. Les conflits
    de salle/chirurgien et les capacites bloc/lits/places restent controles.
    """
    courant = dict(affectation.affectations)
    plage_type = {(p.salle_id, p.creneau_id): p.type_plage
                  for p in instance1.plages_bloc.values()}
    jours = sorted({c.jour for c in instance1.creneaux.values()})
    par_jour = {
        j: sorted((c for c in instance1.creneaux.values() if c.jour == j),
                  key=lambda c: c.heure_debut)
        for j in jours
    }
    occupees: set[tuple[int, int, int]] = set()
    occupe_chir: set[tuple[int, int, int]] = set()
    for v in instance2.vacations.values():
        for cid in v.creneaux_ids:
            occupees.add((v.semaine_decalage, v.salle_id, cid))
            occupe_chir.add((v.semaine_decalage, v.chirurgien_id, cid))

    non_places = sorted(
        (pid for pid, vid in courant.items() if vid is None),
        key=lambda pid: (-instance2.patients[pid].score_priorisation_absente,
                         -instance2.patients[pid].duree_bloc_minutes),
    )
    prochain_id = max(instance2.vacations, default=0) + 1
    h = instance2.parametres_hebergement
    cap_lits = h.lits_disponibles_par_jour - h.reserve_lits
    cap_places = h.places_ambulatoires_par_jour

    for pid in non_places:
        p = instance2.patients[pid]
        # Une insertion dans une vacation existante est toujours preferee a
        # l'ouverture d'une vacation supplementaire.
        etat = EtatNiveau2(instance2, courant)
        options = []
        for v in vacations_compatibles(instance2, p):
            if etat.charge[v.id] + p.duree_bloc_minutes > etat.cap[v.id]:
                continue
            ressource = etat.places if p.ambulatoire else etat.lits
            js = etat._jours_de(pid, v.id)
            if any(ressource.occ.get(j, 0) + 1 > ressource.cap for j in js):
                continue
            options.append((indice_retard_vacation(v),
                            etat.cap[v.id] - etat.charge[v.id] - p.duree_bloc_minutes,
                            v.id))
        if options:
            courant[pid] = min(options)[2]
            continue

        occ_lits, occ_places = calculer_occupation_par_jour(
            instance2, AffectationPatients(courant),
        )
        chir = instance1.chirurgiens[p.chirurgien_id]
        dispo = instance1.disponibilites_chirurgiens.get(p.chirurgien_id)
        salles = sorted(chir.salles_autorisees,
                        key=lambda sid: (sid != chir.salle_preferee, sid))
        nb_creneaux = 2 if p.duree_bloc_minutes > DUREE_CRENEAU_MINUTES * (1 - MARGE_ALEA_VACATION) else 1
        trouvee = None
        for k in range(1, horizon_semaines + 1):
            if trouvee is not None:
                break
            for jour in jours:
                if trouvee is not None:
                    break
                for salle_id in salles:
                    serie = par_jour[jour]
                    for i in range(0, len(serie) - nb_creneaux + 1):
                        groupe = serie[i:i + nb_creneaux]
                        if nb_creneaux == 2 and groupe[0].heure_fin != groupe[1].heure_debut:
                            continue
                        if any(plage_type.get((salle_id, c.id)) == "INDISPONIBLE" for c in groupe):
                            continue
                        if dispo is not None and any(c.id not in dispo for c in groupe):
                            continue
                        if any((k, salle_id, c.id) in occupees for c in groupe):
                            continue
                        if any((k, p.chirurgien_id, c.id) in occupe_chir for c in groupe):
                            continue
                        candidate = Vacation(
                            prochain_id, p.chirurgien_id, salle_id,
                            jour + timedelta(days=7 * k), groupe[0].heure_debut,
                            groupe[-1].heure_fin, tuple(c.id for c in groupe),
                            supplementaire=True, semaine_decalage=k,
                        )
                        js = jours_occupation(p, candidate)
                        occ = occ_places if p.ambulatoire else occ_lits
                        cmax = cap_places if p.ambulatoire else cap_lits
                        if any(occ.get(j, 0) + 1 > cmax for j in js):
                            continue
                        trouvee = candidate
                        break
                    if trouvee is not None:
                        break
        if trouvee is None:
            continue
        instance2.vacations[prochain_id] = trouvee
        courant[pid] = prochain_id
        for cid in trouvee.creneaux_ids:
            occupees.add((trouvee.semaine_decalage, trouvee.salle_id, cid))
            occupe_chir.add((trouvee.semaine_decalage, trouvee.chirurgien_id, cid))
        prochain_id += 1

    resultat = AffectationPatients(courant)
    return resultat, evaluer_affectation(instance2, resultat)


# ----------------------------------------------------------------------
# GENERATION DES PATIENTS
# ----------------------------------------------------------------------

def construire_patients_benchmark(vacations: dict[int, Vacation], nombre_patients: int = 100,
                                  seed: int = 2026) -> dict[int, Patient]:
    """Génère 100 patients synthétiques selon des distributions agrégées historiques.

    Aucun identifiant source n'est réutilisé. Les urgences, priorités et spécialités
    ne sont pas générées car elles sont absentes des fichiers vérifiés.
    """
    rng = random.Random(seed)
    capacites = {}
    for v in vacations.values():
        if not v.supplementaire:
            capacites[v.chirurgien_id] = capacites.get(v.chirurgien_id, 0.0) + duree_vacation_minutes(v)
    chirurgiens = sorted(capacites)
    if not chirurgiens:
        raise ValueError("Aucun chirurgien disponible dans la grille de vacations.")
    codes = sorted(CALIBRATION_SOURCE["besoin_hebdo_par_chirurgien"])
    # Les vacations normalisées sont attribuées par ordre alphabétique des codes.
    poids = []
    for cid in chirurgiens:
        code = codes[cid - 1] if 1 <= cid <= len(codes) else None
        poids.append(CALIBRATION_SOURCE["besoin_hebdo_par_chirurgien"].get(
            code, max(1.0, capacites[cid] / 10.0)))
    patients = {}
    for pid in range(1, nombre_patients + 1):
        cid = rng.choices(chirurgiens, weights=poids, k=1)[0]
        typ = rng.choices(TYPES_INTERVENTION, weights=POIDS_TYPES_INTERVENTION, k=1)[0]
        duree = rng.choices(DUREES_BENCHMARK, weights=POIDS_DUREES_BENCHMARK, k=1)[0]
        sejour_jours = rng.choices(CALIBRATION_SOURCE["sejour_valeurs"],
                                   weights=CALIBRATION_SOURCE["sejour_poids"], k=1)[0]
        # Proxy explicite : 1 jour = ambulatoire (libellé de la colonne source).
        # Pour un séjour > 1, le modèle commence l'occupation le jour de l'opération.
        ambu = sejour_jours == 1
        pre = 0
        post = max(0, sejour_jours - 1)
        patients[pid] = Patient(
            id=pid, nom=f"Patient {pid:03d}", chirurgien_id=cid,
            ambulatoire=ambu, duree_bloc_minutes=duree, nuits_pre_op=pre,
            nuits_post_op=post, type_intervention=typ)
    return patients


INSTANCES_BENCHMARK = {
    "100 patients": {"nombre_patients": 100, "seed": 2026},
}
DUREES_BENCHMARK = CALIBRATION_SOURCE["durees"]
POIDS_DUREES_BENCHMARK = CALIBRATION_SOURCE["poids_durees"]
POIDS_TYPES_BENCHMARK = POIDS_TYPES_INTERVENTION

def diagnostic_coherence_chirurgiens(instance1: InstanceProbleme, instance2: InstanceNiveau2,
                                     semaines_extra: int = 1) -> list[dict]:
    """Audit de cohérence demande/capacité avant et après ouverture possible.

    La capacité « horizon » est une borne haute constructive : les créneaux libres
    sont attribués une seule fois, au chirurgien présentant le plus fort déficit.
    Elle ne remplace pas la validation lits/places, évaluée séparément.
    """
    demande = {cid: 0.0 for cid in instance1.chirurgiens}
    nb_patients = {cid: 0 for cid in instance1.chirurgiens}
    for p in instance2.patients.values():
        demande[p.chirurgien_id] = demande.get(p.chirurgien_id, 0.0) + p.duree_bloc_minutes
        nb_patients[p.chirurgien_id] = nb_patients.get(p.chirurgien_id, 0) + 1
    capacite_reg = {cid: 0.0 for cid in instance1.chirurgiens}
    occupe = set()
    for v in instance2.vacations.values():
        if v.supplementaire:
            continue
        capacite_reg[v.chirurgien_id] += capacite_effective_vacation(v)
        for cid in v.creneaux_ids:
            occupe.add((0, v.salle_id, cid))
    # Attribution gloutonne des créneaux non occupés, en respectant la salle et la disponibilité.
    horizon = dict(capacite_reg)
    plages = {(p.salle_id, p.creneau_id): p.type_plage for p in instance1.plages_bloc.values()}
    creneaux = sorted(instance1.creneaux.values(), key=lambda c: (c.jour, c.heure_debut, c.id))
    for semaine in range(semaines_extra + 1):
        for creneau in creneaux:
            for salle in instance1.salles:
                if plages.get((salle, creneau.id)) != "LIBRE" or (semaine, salle, creneau.id) in occupe:
                    continue
                candidats = []
                for chir in instance1.chirurgiens.values():
                    disponible = instance1.disponibilites_chirurgiens.get(chir.id)
                    if salle in chir.salles_autorisees and (disponible is None or creneau.id in disponible):
                        candidats.append(chir.id)
                if not candidats:
                    continue
                choisi = max(candidats, key=lambda cid: demande.get(cid, 0.0) - horizon.get(cid, 0.0))
                if demande.get(choisi, 0.0) > horizon.get(choisi, 0.0):
                    horizon[choisi] += creneau.duree_minutes * (1 - MARGE_ALEA_VACATION)
                    occupe.add((semaine, salle, creneau.id))
    lignes = []
    for cid, chirurgien in instance1.chirurgiens.items():
        d, c, h = demande.get(cid, 0.0), capacite_reg.get(cid, 0.0), horizon.get(cid, 0.0)
        moyenne = d / nb_patients[cid] if nb_patients[cid] else 0.0
        if d <= c + 1e-9:
            verdict = "COHÉRENT sans vacation supplémentaire"
        elif d <= h + 1e-9:
            verdict = "COHÉRENT avec vacations supplémentaires"
        else:
            verdict = "INCOHÉRENT sur l'horizon : capacité insuffisante"
        lignes.append({
            "Chirurgien": chirurgien.nom,
            "Patients": nb_patients[cid],
            "Demande min": round(d, 1),
            "Capacité régulière min": round(c, 1),
            "Ratio demande/capacité": round(d / c, 2) if c else None,
            "Capacité max horizon min": round(h, 1),
            "Patients théoriques réguliers": int(c // moyenne) if moyenne else 0,
            "Verdict": verdict,
        })
    return lignes


# ----------------------------------------------------------------------
# AFFICHAGE NIVEAU 2
# ----------------------------------------------------------------------

def afficher_scores_par_ressource(ev: EvaluationAffectation, titre="SCORES PAR RESSOURCE (coût à minimiser)"):
    total = ev.score_total or 1.0
    print("┌" + "─" * 86 + "┐")
    print(f"│ {titre:<84} │")
    print("├" + "─" * 86 + "┤")
    print(f"│ {'Ressource':<10}│{'Score':>10} │{'Part':>6} │{'Occ. moy.':>10} │{'Pic':>5} │{'Dépass.':>8} │{'Lissage(var)':>13} │")
    print("├" + "─" * 86 + "┤")
    lignes = [
        ("Blocs", ev.score_blocs, ev.taux_occupation_bloc_pct, "-", f"{ev.violation_capacite_vacation_minutes:.0f}min", "-"),
        ("Lits", ev.score_lits, ev.taux_occupation_lits_pct, ev.pic_lits, str(ev.violation_lits), f"{ev.variance_occupation_lits:.2f}"),
        ("Places", ev.score_places, ev.taux_occupation_places_pct, ev.pic_places, str(ev.violation_places), f"{ev.variance_occupation_places:.2f}"),
    ]
    for nom, sc, occ, pic, dep, var in lignes:
        print(f"│ {nom:<10}│{sc:>10,.0f} │{sc / total * 100:>5.1f}% │{occ:>9.1f}% │{str(pic):>5} │{dep:>8} │{var:>13} │")
    print("├" + "─" * 86 + "┤")
    print(f"│ {'TOTAL':<10}│{ev.score_total:>10,.0f} │{100.0:>5.1f}% │{'':>10} │{'':>5} │{'':>8} │{'':>13} │")
    print("└" + "─" * 86 + "┘")
    if ev.patients_non_places:
        print(f"  ⚠ {ev.patients_non_places} patient(s) non placé(s) (coût inclus dans « Blocs » : "
              f"{ev.patients_non_places * POIDS['non_place']:,})")
    if ev.nb_vacations_supp_utilisees:
        print(f"  ★ {ev.nb_vacations_supp_utilisees} vacation(s) supplémentaire(s) utilisée(s) : {ev.patients_en_supp} patient(s), "
              f"{ev.minutes_en_supp:.0f} min (temps inoccupé NON compté dans « Blocs »)")
    print(f"  Blocs : {ev.temps_bloc_inoccupe_minutes:.0f} min inoccupées (Fbloc, vacations régulières) | "
          f"Lits : {ev.taux_occupation_lits_pct:.0f}% d'occupation moyenne | "
          f"Places : {ev.taux_occupation_places_pct:.0f}% d'occupation moyenne")


def afficher_comparaison(etapes: list):
    """etapes = [(nom, EvaluationAffectation), ...] ; le gain est calculé par rapport à la première."""
    print("\n" + "=" * 86)
    print("  COMPARAISON DES ÉTAPES (score = coût, plus petit = mieux)")
    print("=" * 86)
    print("  " + "".ljust(22) + "".join(f"{nom:>21}" for nom, _ in etapes))
    print("  " + "─" * (22 + 21 * len(etapes)))
    lignes = [("Blocs", "score_blocs"), ("Lits", "score_lits"), ("Places", "score_places"),
              ("TOTAL", "score_total")]
    for nom, attr in lignes:
        print("  " + nom.ljust(22) + "".join(f"{getattr(e, attr):>21,.0f}" for _, e in etapes))
    ref = etapes[0][1].score_total or 1.0
    print("  " + "Gain vs départ".ljust(22) + "".join(f"{(ref - e.score_total) / ref * 100:>20.1f}%" for _, e in etapes))
    print("  " + "─" * (22 + 21 * len(etapes)))
    print("  " + "Patients non placés".ljust(22) + "".join(f"{e.patients_non_places:>21}" for _, e in etapes))
    print("  " + "Dépassement blocs".ljust(22) + "".join(f"{e.violation_capacite_vacation_minutes:>18.0f}min" for _, e in etapes))
    print("  " + "Vacations supp. util.".ljust(22) + "".join(f"{e.nb_vacations_supp_utilisees:>21}" for _, e in etapes))
    print("=" * 86)


def afficher_affectation_patients(instance2, affectation, evaluation,
                                  titre="AFFECTATION DES PATIENTS (NIVEAU 2)"):
    print("=" * 86)
    print(f"  {titre}")
    print("=" * 86)

    par_vac: dict[int, list[int]] = {}
    for pid, vid in affectation.affectations.items():
        if vid is not None:
            par_vac.setdefault(vid, []).append(pid)

    jour_courant = None
    for vac in sorted(instance2.vacations.values(), key=lambda v: (v.jour, v.heure_debut, v.salle_id)):
        if vac.jour != jour_courant:
            jour_courant = vac.jour
            print(f"\n  {JOURS_FR[jour_courant.weekday()].upper()} {jour_courant:%d/%m/%Y}")
            print("  " + "─" * 82)
        nom = instance2.noms_chirurgiens.get(vac.chirurgien_id, f"Chir. {vac.chirurgien_id}")
        pids = sorted(par_vac.get(vac.id, []), key=lambda p: -instance2.patients[p].duree_bloc_minutes)
        charge = sum(instance2.patients[p].duree_bloc_minutes for p in pids)
        cap = capacite_effective_vacation(vac)
        taux = charge / cap * 100 if cap > 0 else 0
        alerte = " ⚠ DÉPASSEMENT" if charge > cap else ""
        if vac.supplementaire:
            alerte += " ★ SUPPL." + (f" (semaine +{vac.semaine_decalage})" if vac.semaine_decalage else " (cette semaine)")
        print(f"  Vac {vac.id:2d} | Salle {vac.salle_id} | {nom:6s} | {vac.heure_debut:%H:%M}-{vac.heure_fin:%H:%M} | "
              f"{barre(charge, cap, 16)} {charge:4.0f}/{cap:.0f} min ({taux:3.0f}%){alerte}")
        for pid in pids:
            p = instance2.patients[pid]
            sejour = ("ambulatoire (sortie le soir)" if p.ambulatoire else
                      f"hospit. {p.nuits_pre_op + p.nuits_post_op + 1} j (veille: {'oui' if p.nuits_pre_op else 'non'})")
            print(f"        · P{p.id:03d} {p.nom:8s} | {p.duree_bloc_minutes:3d} min | {sejour}")

    non_places = [pid for pid, v in affectation.affectations.items() if v is None]
    if non_places:
        print("\n  " + "─" * 82)
        print(f"  PATIENTS NON PLACÉS ({len(non_places)})")
        print("  " + "─" * 82)
        for pid in non_places:
            p = instance2.patients[pid]
            print(f"   - P{p.id:03d} {p.nom:8s} | {instance2.noms_chirurgiens.get(p.chirurgien_id, p.chirurgien_id)} "
                  f"| {p.duree_bloc_minutes} min | {'ambulatoire' if p.ambulatoire else 'hospitalisé'}")

    occ_lits, occ_places = calculer_occupation_par_jour(instance2, affectation)
    h = instance2.parametres_hebergement
    cap_lits, cap_places = h.lits_disponibles_par_jour - h.reserve_lits, h.places_ambulatoires_par_jour
    print("\n  OCCUPATION DES LITS ET PLACES AMBULATOIRES, JOUR PAR JOUR")
    print("  " + "─" * 82)
    for jour in sorted(set(occ_lits) | set(occ_places)):
        l, pl = occ_lits.get(jour, 0), occ_places.get(jour, 0)
        print(f"  {JOURS_FR[jour.weekday()]:9s} {jour:%d/%m} | lits   {barre(l, cap_lits, 14)} {l:2d}/{cap_lits} "
              f"| places {barre(pl, cap_places, 14)} {pl:2d}/{cap_places}")
    print()
    afficher_scores_par_ressource(evaluation)


# ======================================================================
# EXECUTION : NIVEAU 1 PUIS NIVEAU 2
# ======================================================================

# True  : le planning régulier est reconduit la semaine suivante -> seules les plages libres servent.
# False : la semaine suivante est entièrement libre (les chirurgiens y retrouvent toutes leurs disponibilités).
PLANNING_REPETE = False


# ======================================================================
# TABLEAU DE BORD LOCAL — SERVI EN MEMOIRE, AUCUN FICHIER DE RESULTAT
# ======================================================================

def _contexte_optimisation_hybride(instance2):
    pids = sorted(instance2.patients)
    candidats = {pid: [v.id for v in vacations_compatibles(instance2, instance2.patients[pid])] for pid in pids}
    cache = {}
    def evaluer(aff):
        cle = tuple(aff.get(pid) for pid in pids)
        if cle not in cache:
            ev = evaluer_affectation(instance2, AffectationPatients(dict(aff)))
            ok = (ev.patients_non_places == 0 and ev.violation_capacite_vacation_minutes <= 1e-9
                  and ev.violation_lits == 0 and ev.violation_places == 0)
            cache[cle] = (ev.score_total, ev, ok)
        return cache[cle]
    return pids, candidats, evaluer



def optimiser_genetique_niveau2(instance2, depart, graine, taille_population=16,
                                 generations=4, departs_multiples=None, nombre_candidats=1):
    rng = random.Random(graine)
    pids, candidats, evaluer = _contexte_optimisation_hybride(instance2)
    population = []
    for source in departs_multiples or [depart]:
        aff = dict(source.affectations); score, _, ok = evaluer(aff)
        sig = tuple(aff.get(pid) for pid in pids)
        if ok and all(tuple(a.get(pid) for pid in pids) != sig for _, a in population):
            population.append((score, aff))
    if not population:
        ev = evaluer_affectation(instance2, depart)
        return (depart, ev) if nombre_candidats == 1 else [(depart, ev)]
    population.sort(key=lambda x: x[0]); base = dict(population[0][1])
    while len(population) < taille_population:
        ind = dict(base)
        for pid in rng.sample(pids, min(rng.randint(1, max(1, min(8, len(pids)//12+1))), len(pids))):
            cs = [v for v in candidats[pid] if v != ind.get(pid)]
            if cs: ind[pid] = rng.choice(cs)
        score, _, ok = evaluer(ind)
        population.append((score, ind) if ok else (population[0][0], dict(base)))
    bestscore, best = min(population, key=lambda x: x[0])
    def tournoi(): return min(rng.sample(population, min(3, len(population))), key=lambda x: x[0])[1]
    for _ in range(generations):
        population.sort(key=lambda x: x[0]); nxt = [(sc, dict(a)) for sc, a in population[:max(1, taille_population//4)]]
        while len(nxt) < taille_population:
            p1, p2 = tournoi(), tournoi(); child = dict(p1)
            for pid in rng.sample(pids, min(len(pids), max(1, min(12, len(pids)//15+1)))):
                if rng.random() < .5 and child.get(pid) != p2.get(pid):
                    trial = dict(child); trial[pid] = p2.get(pid)
                    if evaluer(trial)[2]: child = trial
            for pid in rng.sample(pids, min(len(pids), max(1, min(4, len(pids)//50+1)))):
                cs = [v for v in candidats[pid] if v != child.get(pid)]
                if cs:
                    trial = dict(child); trial[pid] = rng.choice(cs)
                    if evaluer(trial)[2]: child = trial
            score, _, ok = evaluer(child)
            if not ok: child = dict(p1); score = evaluer(child)[0]
            nxt.append((score, child))
            if score < bestscore: bestscore, best = score, dict(child)
        population = nxt
    pool = sorted(population + [(bestscore, best)], key=lambda x: x[0]); results=[]; seen=set()
    for _, aff in pool:
        sig = tuple(aff.get(pid) for pid in pids)
        if sig in seen: continue
        seen.add(sig); sol = AffectationPatients(dict(aff)); results.append((sol, evaluer_affectation(instance2, sol)))
        if len(results) >= max(1, nombre_candidats): break
    return results[0] if nombre_candidats == 1 else results


def optimiser_recuit_simule_niveau2(instance2, depart, graine, iterations):
    rng=random.Random(graine); pids,candidats,evaluer=_contexte_optimisation_hybride(instance2)
    cur=dict(depart.affectations); score,ev,ok=evaluer(cur)
    if not ok or not pids or iterations<=0: return depart,ev
    best=dict(cur); bestscore=score; temp=max(1.,abs(score)*.002)
    alpha=(.02/temp)**(1.0/max(1,iterations))
    for _ in range(iterations):
        pid=rng.choice(pids); cs=[v for v in candidats[pid] if v!=cur.get(pid)]
        if cs:
            trial=dict(cur); trial[pid]=rng.choice(cs); sv,_,valid=evaluer(trial)
            if valid and (sv<=score or rng.random()<math.exp(-min((sv-score)/temp,700.))):
                cur,score=trial,sv
                if score<bestscore: best,bestscore=dict(cur),score
        temp=max(.02,temp*alpha)
    sol=AffectationPatients(best); return sol,evaluer_affectation(instance2,sol)




def chercher_horizon_plus_court(instance2, affectation, graine, rapide=False):
    """Teste des horizons plus courts avec répétition hebdomadaire des vacations régulières.

    Il s'agit d'une recherche heuristique multi-départs : l'échec à trouver un
    planning plus court ne prouve pas qu'il est mathématiquement impossible.
    """
    horizon_actuel = max(
        (instance2.vacations[vid].semaine_decalage + 1
         for vid in affectation.affectations.values() if vid is not None),
        default=1,
    )
    for nb_semaines in range(1, horizon_actuel):
        # Les vacations régulières sont hebdomadaires : les recréer pour chaque
        # semaine du candidat évite de traiter à tort les semaines suivantes
        # comme si seules des heures supplémentaires y étaient disponibles.
        regulieres = [v for v in instance2.vacations.values()
                      if not v.supplementaire and v.semaine_decalage == 0]
        vacations_courtes = {v.id: v for v in regulieres}
        prochain_id = max(instance2.vacations, default=0) + 1
        for semaine in range(1, nb_semaines):
            for v in regulieres:
                vacations_courtes[prochain_id] = replace(
                    v,
                    id=prochain_id,
                    jour=v.jour + timedelta(days=7 * semaine),
                    semaine_decalage=semaine,
                )
                prochain_id += 1
        vacations_courtes.update({
            vid: vac for vid, vac in instance2.vacations.items()
            if vac.supplementaire and vac.semaine_decalage < nb_semaines
        })
        if not vacations_courtes:
            continue
        essai = InstanceNiveau2(
            patients=instance2.patients,
            vacations=vacations_courtes,
            parametres_hebergement=instance2.parametres_hebergement,
            noms_chirurgiens=instance2.noms_chirurgiens,
        )
        candidat = construire_meilleure_affectation_initiale(
            essai,
            nb_essais=12 if rapide else 48,
            graine=graine + nb_semaines * 104729,
        )
        evaluation = evaluer_affectation(essai, candidat)
        faisable = (
            evaluation.patients_non_places == 0
            and evaluation.violation_capacite_vacation_minutes <= 1e-9
            and evaluation.violation_lits == 0
            and evaluation.violation_places == 0
        )
        if not faisable:
            continue
        if faisable:
            return essai, candidat, evaluation
    return instance2, affectation, evaluer_affectation(instance2, affectation)


HYBRIDATIONS = [
    ("AG → Tabou → Recuit", "AG → Tabou → Recuit"),
    ("Tabou → AG → Recuit", "Tabou → AG → Recuit"),
    ("Recuit → Tabou → AG", "Recuit → Tabou → AG"),
    ("Recuit → AG → Tabou", "Recuit → AG → Tabou"),
    ("AG + fils → Recuit → Tabou → AG", "AG: garder les meilleurs fils → recuit sur chaque fils → tabou sur chaque fils → réintégration et fin de l'AG"),
]


def est_solution_faisable(evaluation):
    return (evaluation.patients_non_places == 0
            and evaluation.violation_capacite_vacation_minutes <= 1e-9
            and evaluation.violation_lits == 0
            and evaluation.violation_places == 0)


def preparer_solution_commune(instance1, vacations_base, patients, config, rapide):
    """Construit une même solution initiale faisable pour les cinq méthodes."""
    hebergement = ParametresHebergement(lits_disponibles_par_jour=14,
                                        places_ambulatoires_par_jour=10,
                                        reserve_lits=2)
    instance2 = InstanceNiveau2(
        dict(patients), copy.deepcopy(vacations_base), hebergement,
        {cid: c.nom for cid, c in instance1.chirurgiens.items()},
    )
    solution = construire_meilleure_affectation_initiale(
        instance2, nb_essais=12 if rapide else 24, graine=config['seed'],
    )
    solution, evaluation = optimiser_avec_vacations_supplementaires(
        instance1, instance2, solution, max_tours=10, semaines_extra=8,
        planning_repete=True, temps_par_tour=.6 if rapide else 1.5,
        verbose=False, graine=config['seed'] + 1,
    )
    solution, evaluation = reparer_non_places_par_chirurgien(
        instance2, solution, graine=config['seed'] + 2,
        temps_max_secondes=1.0 if rapide else 5.0,
    )
    if evaluation.patients_non_places:
        solution, evaluation = garantir_placement_restant(
            instance1, instance2, solution, horizon_semaines=20,
        )
    if not est_solution_faisable(evaluation):
        raise RuntimeError(
            "Impossible de construire un planning initial faisable; "
            "la comparaison des cinq hybridations est arrêtée."
        )
    # Trouve un horizon de départ court sans lancer l'une des métaheuristiques.
    instance2, solution, evaluation = chercher_horizon_plus_court(
        instance2, solution, config['seed'] + 838383, rapide=rapide,
    )
    if not est_solution_faisable(evaluation):
        raise RuntimeError("Le planning commun n'est plus faisable après la recherche d'horizon.")
    return instance2, solution


def optimiser_instance_benchmark(nom, description, config, instance2_base,
                                 depart_commun, instance1, rapide):
    """Exécute une des cinq chaînes depuis la même instance et le même départ."""
    debut = chrono.perf_counter()
    instance2 = copy.deepcopy(instance2_base)
    depart = depart_commun.copy()
    population = 6 if rapide else 16
    generations = 2 if rapide else 4
    candidats = 3
    recuit_iterations = 80 if rapide else 800
    tabou_seconds = .25 if rapide else 2.0
    tabou_exchanges = 300
    base_seed = config['seed'] + 1000003 * (HYBRIDATIONS.index((nom, description)) + 1)
    scores_etapes = {}

    def generique(source, offset):
        found = optimiser_genetique_niveau2(
            instance2, source, base_seed + offset, population, generations,
            nombre_candidats=candidats,
        )
        if isinstance(found, tuple):
            found = [found]
        found.sort(key=lambda item: item[1].score_total)
        scores_etapes['Génétique'] = round(found[0][1].score_total, 2)
        return found

    def tabou(source, offset):
        solution, evaluation = lancer_tabou_niveau2(
            instance2, source, temps_max_secondes=tabou_seconds,
            patience=100, nb_echanges_par_iteration=tabou_exchanges,
            graine=base_seed + offset, verbose=False,
        )
        scores_etapes['Tabou'] = round(evaluation.score_total, 2)
        return solution, evaluation

    def recuit(source, offset):
        solution, evaluation = optimiser_recuit_simule_niveau2(
            instance2, source, base_seed + offset, recuit_iterations,
        )
        scores_etapes['Recuit'] = round(evaluation.score_total, 2)
        return solution, evaluation

    if nom == "AG → Tabou → Recuit":
        fils = generique(depart, 101)
        final, _ = tabou(fils[0][0], 211)
        final, evaluation = recuit(final, 307)
    elif nom == "Tabou → AG → Recuit":
        courant, _ = tabou(depart, 401)
        fils = generique(courant, 503)
        final, evaluation = recuit(fils[0][0], 601)
    elif nom == "Recuit → Tabou → AG":
        courant, _ = recuit(depart, 701)
        courant, _ = tabou(courant, 809)
        fils = generique(courant, 907)
        final, evaluation = fils[0]
    elif nom == "Recuit → AG → Tabou":
        courant, _ = recuit(depart, 1009)
        fils = generique(courant, 1103)
        final, evaluation = tabou(fils[0][0], 1201)
    else:
        # Variante à fils : le premier AG produit trois solutions faisables.
        enfants_ga = generique(depart, 1301)
        enfants_recuit = [
            optimiser_recuit_simule_niveau2(
                instance2, fils, base_seed + 1409 + k * 97, recuit_iterations,
            ) for k, (fils, _) in enumerate(enfants_ga)
        ]
        scores_etapes['Recuit sur fils'] = round(
            min(ev.score_total for _, ev in enfants_recuit), 2,
        )
        enfants_tabou = [
            lancer_tabou_niveau2(
                instance2, fils, temps_max_secondes=tabou_seconds,
                patience=100, nb_echanges_par_iteration=tabou_exchanges,
                graine=base_seed + 1601 + k * 101, verbose=False,
            ) for k, (fils, _) in enumerate(enfants_recuit)
        ]
        scores_etapes['Tabou sur fils'] = round(
            min(ev.score_total for _, ev in enfants_tabou), 2,
        )
        final, evaluation = optimiser_genetique_niveau2(
            instance2, enfants_tabou[0][0], base_seed + 1801,
            population, generations,
            departs_multiples=[sol for sol, _ in enfants_tabou],
            nombre_candidats=1,
        )
        scores_etapes['Génétique final'] = round(evaluation.score_total, 2)

    if not est_solution_faisable(evaluation):
        raise RuntimeError(f"La chaîne {nom} a produit une solution non faisable.")
    semaine_max = max(
        (instance2.vacations[vid].semaine_decalage
         for vid in final.affectations.values() if vid is not None),
        default=0,
    )
    coherence = diagnostic_coherence_chirurgiens(instance1, instance2, semaines_extra=12)
    nb_patients = len(instance2.patients)
    ligne = {
        'Instance': nom, 'Patients': nb_patients,
        'Placés': nb_patients - evaluation.patients_non_places,
        'Non placés': evaluation.patients_non_places,
        'Semaines nécessaires': semaine_max + 1,
        'Score blocs': round(evaluation.score_blocs, 2),
        'Score lits': round(evaluation.score_lits, 2),
        'Score places': round(evaluation.score_places, 2),
        'Score total': round(evaluation.score_total, 2),
        'Dépassement bloc (min)': round(evaluation.violation_capacite_vacation_minutes, 2),
        'Violation lits': evaluation.violation_lits,
        'Violation places': evaluation.violation_places,
        'Contraintes': 'OK',
        'Vacations supplémentaires': evaluation.nb_vacations_supp_utilisees,
        'Séquence': description,
        'Temps (s)': round(chrono.perf_counter() - debut, 1),
    }
    return {
        'nom': nom, 'patients': instance2.patients, 'instance': instance2,
        'affectation': final, 'evaluation': evaluation,
        'coherence': coherence,
        'progression_hybride': {'scores': scores_etapes, 'ordre': description},
        'ligne': ligne,
    }


def planning_visuel_instance(resultat):
    instance2=resultat['instance']; affectation=resultat['affectation']; par_vac={}
    for pid,vid in affectation.affectations.items():
        if vid is not None: par_vac.setdefault(vid,[]).append(instance2.patients[pid])
    lignes=[]
    for vac in sorted(instance2.vacations.values(),key=lambda v:(v.semaine_decalage,v.jour,v.salle_id,v.heure_debut)):
        ps=sorted(par_vac.get(vac.id,[]),key=lambda p:-p.duree_bloc_minutes)
        if not ps: continue
        charge=sum(p.duree_bloc_minutes for p in ps); cap=capacite_effective_vacation(vac)
        lignes.append({'Instance':resultat['nom'],'Semaine':vac.semaine_decalage,'Jour':JOURS_FR[vac.jour.weekday()],
            'Ordre jour':vac.jour.weekday(),'Date':vac.jour.strftime('%d/%m/%Y'),'Salle':vac.salle_id,'Vacation':vac.id,
            'Début':vac.heure_debut.strftime('%H:%M'),'Fin':vac.heure_fin.strftime('%H:%M'),
            'Chirurgien':instance2.noms_chirurgiens.get(vac.chirurgien_id,str(vac.chirurgien_id)),
            'Supplémentaire':vac.supplementaire,'Charge':charge,'Capacité':round(cap,1),
            'Occupation':round(100*charge/cap,1) if cap else 0.,
            'Patients':[{'nom':p.nom,'duree':p.duree_bloc_minutes,'intervention':p.type_intervention} for p in ps]})
    return lignes


def lignes_patients_dashboard(instance2: InstanceNiveau2, affectation: AffectationPatients) -> list[dict]:
    lignes = []
    for p in instance2.patients.values():
        vid = affectation.affectations[p.id]
        v = instance2.vacations.get(vid) if vid is not None else None
        lignes.append({
            "Patient": p.nom,
            "Chirurgien": instance2.noms_chirurgiens.get(p.chirurgien_id, str(p.chirurgien_id)),
            "Intervention": p.type_intervention,
            "Durée": p.duree_bloc_minutes,
            "Statut": "PLACÉ" if v else "NON PLACÉ",
            "Créneau": (f"S+{v.semaine_decalage} · {JOURS_FR[v.jour.weekday()]} {v.jour:%d/%m} {v.heure_debut:%H:%M} · salle {v.salle_id}" if v else "—"),
        })
    return sorted(lignes, key=lambda x: (x["Statut"] != "PLACÉ", x["Créneau"]))


def page_dashboard_instances(resultats: list[dict]) -> str:
    lignes = [r['ligne'] for r in resultats]
    data = json.dumps(lignes, ensure_ascii=False).replace('</', '<\\/')
    template = r"""<!doctype html><html lang="fr"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Comparaison des hybridations</title>
<style>body{font-family:Segoe UI,Arial,sans-serif;background:#f3f8f4;color:#173b27;margin:0}header{background:#14532d;color:white;padding:28px 5%}main{padding:24px 5%}.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:12px}.card,.panel{background:white;border:1px solid #d6e7da;border-radius:14px;padding:16px;margin:12px 0}.big{font-size:27px;font-weight:700}table{border-collapse:collapse;width:100%;background:white}th,td{text-align:left;padding:11px;border-bottom:1px solid #e3eee5}th{background:#e8f4eb;position:sticky;top:0}.table{overflow:auto;max-height:68vh}.bar{height:10px;background:#e6efe8;border-radius:8px;min-width:120px}.fill{height:100%;background:#16803e;border-radius:8px}.sub{color:#cce8d4}h1{margin:5px 0 8px}</style>
<header><p>COMPARAISON EXPÉRIMENTALE · INSTANCE UNIQUE DE 100 PATIENTS</p><h1>Cinq hybridations, même départ</h1><div class="sub">Même cohorte, mêmes capacités, mêmes contraintes de faisabilité. Le score le plus bas est préférable parmi les solutions faisables.</div></header><main><div id="cards" class="cards"></div><section class="panel"><h2>Scores finaux</h2><div class="table" id="results"></div></section><section class="panel"><h2>Score total comparé</h2><div id="bars"></div><p>La durée de calcul est également indiquée; certaines chaînes traitent plusieurs fils et peuvent donc demander davantage de calcul.</p></section></main>
<script>const D=__DATA__;const n=x=>new Intl.NumberFormat('fr-FR',{maximumFractionDigits:2}).format(x??0),e=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));const best=Math.min(...D.filter(x=>x.Contraintes==='OK').map(x=>x['Score total']));document.getElementById('cards').innerHTML=[['Méthodes comparées',D.length],['Patients par méthode',D[0]?.Patients??0],['Meilleur score faisable',n(best)],['Score le plus bas',D.find(x=>x['Score total']===best)?.Instance??'—']].map(x=>`<article class="card"><b>${e(x[0])}</b><div class="big">${e(x[1])}</div></article>`).join('');const cols=['Instance','Séquence','Placés','Semaines nécessaires','Score blocs','Score lits','Score places','Score total','Contraintes','Temps (s)'];document.getElementById('results').innerHTML='<table><thead><tr>'+cols.map(c=>`<th>${e(c)}</th>`).join('')+'</tr></thead><tbody>'+D.map(r=>'<tr>'+cols.map(c=>`<td>${e(typeof r[c]==='number'?n(r[c]):r[c])}</td>`).join('')+'</tr>').join('')+'</tbody></table>';const max=Math.max(...D.map(r=>r['Score total']),1);document.getElementById('bars').innerHTML=D.map(r=>`<div style="display:grid;grid-template-columns:260px 1fr 100px;gap:12px;align-items:center;margin:12px 0"><b>${e(r.Instance)}</b><div class="bar"><div class="fill" style="width:${Math.max(1,100*r['Score total']/max)}%"></div></div><span>${n(r['Score total'])}</span></div>`).join('');</script></main></html>"""
    return template.replace('__DATA__', data)

def ouvrir_dashboard_instances(resultats: list[dict]) -> None:
    import threading, webbrowser
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    contenu = page_dashboard_instances(resultats).encode("utf-8")
    class Gestionnaire(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(contenu))); self.end_headers(); self.wfile.write(contenu)
        def log_message(self, *_): return
    serveur = ThreadingHTTPServer(("127.0.0.1", 0), Gestionnaire)
    url = f"http://127.0.0.1:{serveur.server_port}/"
    threading.Timer(.25, lambda: webbrowser.open(url)).start()
    print(f"Dashboard tabou : {url}\nAucun fichier de résultat créé. Ctrl+C pour arrêter.")
    try: serveur.serve_forever()
    except KeyboardInterrupt: pass
    finally: serveur.server_close()


def executer_comparatif(rapide: bool = False, verbose: bool = True,
                        historique: Path = SOURCE_HISTORIQUE_DEFAUT,
                        vacations_source: Path = SOURCE_VACATIONS_DEFAUT,
                        seed: Optional[int] = None) -> list[dict]:
    """Génère et optimise une instance unique de 100 patients.

    Cette fonction est l'entrée réutilisable du notebook. Elle ne lance pas le
    serveur web et n'écrit aucun fichier de résultats.
    """
    controle_historique = verifier_fichier_source(historique, HASH_HISTORIQUE_ATTENDU)
    controle_vacations = verifier_fichier_source(vacations_source, HASH_VACATIONS_ATTENDU)
    if verbose:
        print("Sources Excel :", flush=True)
        print(f"  historique : {'OK' if controle_historique['hash_ok'] else 'calibration embarquee'}", flush=True)
        print(f"  vacations  : {'OK' if controle_vacations['hash_ok'] else 'normalisation embarquee'}", flush=True)
    instance1, vacations_base = construire_instance_depuis_vacations_source()
    seed = seed if seed is not None else random.SystemRandom().randrange(1, 2**31)
    config_instance = {"nombre_patients": 100, "seed": seed}
    patients_maitres = construire_patients_benchmark(vacations_base, 100, seed)
    sources = {
        "historique": controle_historique,
        "vacations": controle_vacations,
        "audit": {
            "Interventions historiques": CALIBRATION_SOURCE["lignes"],
            "Libellés d’actes distincts": 1433,
            "Lignes sans libellé d’acte": 137,
            "Libellés utilisés par le générateur": len(TYPES_INTERVENTION),
            "Patients distincts": CALIBRATION_SOURCE["patients_distincts"],
            "Durées exploitables": CALIBRATION_SOURCE["lignes_duree_valides"],
            "Horaires exclus": CALIBRATION_SOURCE["horaires_invalides"],
            "Période": f"{CALIBRATION_SOURCE['premiere_date']} au {CALIBRATION_SOURCE['derniere_date']}",
            "Vacations normalisées": len(VACATIONS_SOURCE_NORMALISEES),
            "Salles source": 4,
            "Chirurgiens anonymisés": len(instance1.chirurgiens),
            "Minutes régulières source": sum(duree_vacation_minutes(v) for v in vacations_base.values()),
        },
        "limites": [
            "Une cohorte synthétique unique de 100 patients est générée à partir de distributions agrégées ; aucun identifiant patient source n’est repris.",
            "Le séjour source de 1 jour est traité comme ambulatoire; sinon l'occupation commence le jour de l'opération, sans pré-hospitalisation (approximation).",
            "Les caractéristiques sont tirées indépendamment de distributions marginales agrégées; les corrélations entre acte, durée, séjour et chirurgien ne sont pas conservées.",
            "Les urgences, priorités et spécialités sont absentes des sources et ne sont pas modélisées.",
            "La disponibilité future est supposée identique aux jours où le chirurgien apparaît dans la grille source.",
        ],
    }
    sources["audit"]["Graine aléatoire"] = seed
    resultats = []
    nom_base = {"nombre_patients": 100, "seed": seed}
    if verbose:
        print("Construction du départ commun faisable pour les cinq chaînes…", flush=True)
    instance2_base, depart_commun = preparer_solution_commune(
        instance1, vacations_base, patients_maitres, nom_base, rapide,
    )
    for nom, description in HYBRIDATIONS:
        if verbose:
            print(f"\nComparaison : {nom}", flush=True)
        resultat = optimiser_instance_benchmark(
            nom, description, nom_base, instance2_base, depart_commun,
            instance1, rapide,
        )
        resultat["sources"] = sources
        resultats.append(resultat)
        ligne = resultat["ligne"]
        if verbose:
            print(
                f"  {ligne['Placés']}/{ligne['Patients']} placés; "
                f"{ligne['Semaines nécessaires']} semaine(s); "
                f"score={ligne['Score total']:,.2f}; contraintes={ligne['Contraintes']}; "
                f"temps={ligne['Temps (s)']:.1f}s",
                flush=True,
            )
    if resultats:
        meilleur = min(resultats, key=lambda r: r['ligne']['Score total'])
        if verbose:
            print(f"\nMeilleur score faisable : {meilleur['nom']} — "
                  f"{meilleur['ligne']['Score total']:,.2f}", flush=True)
    return resultats


# ======================================================================
# SORTIE TEXTE STRUCTUREE — MEME ORGANISATION QUE LE CODE DE REFERENCE
# ======================================================================

def libelle_jour(jour: date) -> str:
    """Libellé homogène avec le rapport texte du code de référence."""
    return f"{jour.isoformat()} ({JOURS_FR[jour.weekday()].lower()})"


def _semaine_max_utilisee(resultat: dict) -> int:
    affectation: AffectationPatients = resultat["affectation"]
    instance2: InstanceNiveau2 = resultat["instance"]
    semaines = [
        instance2.vacations[vid].semaine_decalage
        for vid in affectation.affectations.values() if vid is not None
    ]
    return max(semaines, default=0) + 1


def _occupation_vacations(instance2: InstanceNiveau2,
                          affectation: AffectationPatients) -> dict[int, list[int]]:
    par_vacation: dict[int, list[int]] = {}
    for patient_id, vacation_id in affectation.affectations.items():
        if vacation_id is not None:
            par_vacation.setdefault(vacation_id, []).append(patient_id)
    return par_vacation


def verifier_capacites_finales(instance2: InstanceNiveau2,
                               affectation: AffectationPatients) -> dict:
    """Recalcule indépendamment les pics de charge du planning final."""
    par_vacation = _occupation_vacations(instance2, affectation)
    taux_bloc = 0.0
    for vacation_id, patients_ids in par_vacation.items():
        charge = sum(instance2.patients[pid].duree_bloc_minutes for pid in patients_ids)
        capacite = capacite_effective_vacation(instance2.vacations[vacation_id])
        taux_bloc = max(taux_bloc, 100.0 * charge / capacite if capacite > 0 else float("inf"))

    occ_lits, occ_places = calculer_occupation_par_jour(instance2, affectation)
    h = instance2.parametres_hebergement
    capacite_lits = h.lits_disponibles_par_jour - h.reserve_lits
    capacite_places = h.places_ambulatoires_par_jour

    def taux_max(occupation: dict[date, int], capacite: int) -> float:
        if not occupation:
            return 0.0
        if capacite <= 0:
            return float("inf")
        return max(100.0 * valeur / capacite for valeur in occupation.values())

    taux_lits = taux_max(occ_lits, capacite_lits)
    taux_places = taux_max(occ_places, capacite_places)
    return {
        "taux_max_bloc": taux_bloc,
        "taux_max_lits": taux_lits,
        "taux_max_places": taux_places,
        "ok": max(taux_bloc, taux_lits, taux_places) <= 100.0 + 1e-9,
    }


def afficher_sources_console(resultats: list[dict]) -> None:
    sources = resultats[0]["sources"] if resultats else {}
    audit = sources.get("audit", {})
    print("=" * 104)
    print("DONNEES SOURCES — CONTROLE ET CALIBRATION")
    print("=" * 104)
    print(f"  Historique anonymisé : {'empreinte vérifiée' if sources.get('historique', {}).get('hash_ok') else 'absent ou différent'}")
    print(f"  Vacations anonymisées : {'empreinte vérifiée' if sources.get('vacations', {}).get('hash_ok') else 'absent ou différent'}")
    for nom, valeur in audit.items():
        print(f"  {nom:<28}: {valeur}")
    print("  Aucune donnée d’urgence, de priorité ou de spécialité n’est disponible dans les sources.")


def afficher_niveau1_console(resultats: list[dict]) -> None:
    if not resultats:
        return
    instance2: InstanceNiveau2 = resultats[0]["instance"]
    base = [v for v in instance2.vacations.values()
            if not v.supplementaire and v.semaine_decalage == 0]
    semaines = max((v.semaine_decalage for v in instance2.vacations.values()), default=0) + 1
    print("\nNIVEAU 1 — BASE COMMUNE AUX CINQ MÉTHODES")
    print(f"  Grille source : {len(base)} vacations régulières par semaine.")
    print(f"  Grille répétée sur {semaines} semaine(s) pour le planning comparé.")


def afficher_benchmark_console(resultats: list[dict]) -> None:
    print("\nCOMPARAISON DES CINQ HYBRIDATIONS")
    colonnes = ("Hybridation", "Placés", "Sem.", "Blocs", "Lits", "Places", "Total", "Temps", "Faisable")
    print(f"{colonnes[0]:<34} {colonnes[1]:>7} {colonnes[2]:>4} {colonnes[3]:>9} {colonnes[4]:>9} {colonnes[5]:>9} {colonnes[6]:>10} {colonnes[7]:>7} {colonnes[8]:>9}")
    print("-" * 110)
    for resultat in sorted(resultats, key=lambda r: r['ligne']['Score total']):
        x = resultat['ligne']
        print(f"{x['Instance'][:34]:<34} {x['Placés']:>3}/{x['Patients']:<3} {x['Semaines nécessaires']:>4} {x['Score blocs']:>9.2f} {x['Score lits']:>9.2f} {x['Score places']:>9.2f} {x['Score total']:>10.2f} {x['Temps (s)']:>6.1f}s {x['Contraintes']:>9}")

def afficher_rapport_niveau2_console(resultat: dict, detail: bool = True) -> None:
    instance2 = resultat["instance"]
    affectation = resultat["affectation"]
    evaluation = resultat["evaluation"]
    verification = verifier_capacites_finales(instance2, affectation)
    occ_lits, occ_places = calculer_occupation_par_jour(instance2, affectation)
    total = len(instance2.patients)
    print(f"\nRapport — {resultat['nom']} : {total} patients, {resultat['ligne']['Semaines nécessaires']} semaine(s) de planning, score {evaluation.score_total:.2f}")
    print(f"  Blocs {evaluation.score_blocs:.2f} | lits {evaluation.score_lits:.2f} | places {evaluation.score_places:.2f}")
    print(f"  Placés {total-evaluation.patients_non_places}/{total} | vacations supplémentaires {evaluation.nb_vacations_supp_utilisees}")
    print(f"  Capacités : {'OK' if verification['ok'] else 'À CORRIGER'} "
          f"(bloc {verification['taux_max_bloc']:.0f} %, lits {verification['taux_max_lits']:.0f} %, places {verification['taux_max_places']:.0f} %)")
    if not detail:
        return
    print("  Patients :")
    for pid, patient in sorted(instance2.patients.items()):
        vid = affectation.affectations.get(pid)
        if vid is None:
            print(f"    {patient.nom}: non placé")
            continue
        v = instance2.vacations[vid]
        chir = instance2.noms_chirurgiens.get(patient.chirurgien_id, str(patient.chirurgien_id))
        print(f"    {patient.nom}: {patient.duree_bloc_minutes} min, {patient.type_intervention}, "
              f"{chir}, salle {v.salle_id}, {libelle_jour(v.jour)}, semaine +{v.semaine_decalage}")


def afficher_sortie_console(resultats: list[dict], detail: str = "100 patients") -> None:
    """Affiche uniquement du texte ; aucun serveur, navigateur ou fichier résultat."""
    afficher_sources_console(resultats)
    afficher_niveau1_console(resultats)
    afficher_benchmark_console(resultats)
    if detail == "Aucun":
        return
    selection = resultats if detail == "Toutes" else [r for r in resultats if r["nom"] == detail]
    for resultat in selection:
        afficher_rapport_niveau2_console(resultat, detail=True)


if __name__ == "__main__":
    arguments = argparse.ArgumentParser(
        description="Comparaison de cinq hybridations sur la même instance aléatoire de 100 patients."
    )
    arguments.add_argument("--sans-interface", action="store_true",
                           help="Valide les calculs et imprime les résultats sans ouvrir le site.")
    arguments.add_argument("--rapide", action="store_true", help="Budget court pour test technique.")
    arguments.add_argument("--seed", type=int, default=None, help="Graine optionnelle pour reproduire la cohorte aléatoire.")
    arguments.add_argument("--historique", type=Path, default=SOURCE_HISTORIQUE_DEFAUT)
    arguments.add_argument("--vacations", type=Path, default=SOURCE_VACATIONS_DEFAUT)
    options = arguments.parse_args()
    t_global = chrono.perf_counter()
    resultats = executer_comparatif(
        rapide=options.rapide, verbose=True,
        historique=options.historique, vacations_source=options.vacations, seed=options.seed,
    )
    print(f"Comparaison terminée en {chrono.perf_counter() - t_global:.1f}s", flush=True)
    if options.sans_interface:
        afficher_sortie_console(resultats, detail="Aucun")
    else:
        ouvrir_dashboard_instances(resultats)




