<?php
define('IN_SCRIPT', 1);
define('HESK_PATH', '../');
require_once('Rabbitmq.php');
require(HESK_PATH . 'hesk_settings.inc.php');
require(HESK_PATH . 'inc/common.inc.php');
require_once('database.php');

hesk_load_database_functions();
hesk_dbConnect();

// echo hesk_dbEscape('admin');
// exit;

try{
    $listener = new Rabbitmq_client();
}catch(Exception $e){
    
    if(strpos("stream_socket_client(): unable to connect to tcp://10.50.125.79:5672 (Connection timed out)", 'unable') !== false){
        echo "Error: Queue connection failed. Please contact to system administrator. <br/>
        Original Message: " . $e->getMessage();
    }else{
        echo $e->getMessage();
    }
}

$listenQueue = 'ag_pension_hrmis_common';
//$listenQueue = 'ag_pension_sngad_staging';
$listenTag = 'normal';
$permanent = true;

function createDirectory($key=null,$img=null,$retirement_id=null,$department_name){
    $department_name_folder = strtolower($department_name);
    if (!file_exists("../ticket_images_$department_name_folder") && !is_dir("../ticket_images_$department_name_folder")) {
        mkdir("../ticket_images_$department_name_folder",0777,true);
        chmod("../ticket_images_$department_name_folder", 0755);      
    }
    if (!file_exists("../ticket_images_$department_name_folder/$key") && !is_dir("../ticket_images_$department_name_folder/$key")) {
        mkdir("../ticket_images_$department_name_folder/$key",0777,true);
        chmod("../ticket_images_$department_name_folder/$key", 0755);        
    }
    if($key!='officer_signature'){
       if (!file_exists("../ticket_images_$department_name_folder/$key/retirement") && !is_dir("../ticket_images_$department_name_folder/$key/retirement")) {
          mkdir("../ticket_images_$department_name_folder/$key/retirement",0777,true);
          chmod("../ticket_images_$department_name_folder/$key/retirement", 0755);      
       }
       if (!file_exists("../ticket_images_$department_name_folder/$key/retirement/$retirement_id") && !is_dir("../ticket_images_$department_name_folder/$key/retirement/$retirement_id")) {
          mkdir("../ticket_images_$department_name_folder/$key/retirement/$retirement_id",0777,true);
          chmod("../ticket_images_$department_name_folder/$key/retirement/$retirement_id", 0755);      
       }
    }

}

function createHistoryDirectory($ticket_id,$key=null,$img=null,$retirement_id=null,$department_name){
    $department_name_folder = strtolower($department_name);
    if (!file_exists("../ticket_images_history_$department_name_folder") && !is_dir("../ticket_images_history_$department_name_folder")) {
       mkdir("../ticket_images_history_$department_name_folder",0777,true);
       chmod("../ticket_images_history_$department_name_folder", 0777);      
    }
    if (!file_exists("../ticket_images_history_$department_name_folder/$ticket_id") && !is_dir("../ticket_images_history_$department_name_folder/$ticket_id")) {
       mkdir("../ticket_images_history_$department_name_folder/$ticket_id",0777,true);
       chmod("../ticket_images_history_$department_name_folder/$ticket_id", 0777);
    }
    if (!file_exists("../ticket_images_history_$department_name_folder/$ticket_id/$key") && !is_dir("../ticket_images_history_$department_name_folder/$ticket_id/$key")) {
       mkdir("../ticket_images_history_$department_name_folder/$ticket_id/$key",0777,true);
       chmod("../ticket_images_history_$department_name_folder/$ticket_id/$key", 0777);        
    }
    if (!file_exists("../ticket_images_history_$department_name_folder/$ticket_id/$key/retirement") && !is_dir("../ticket_images_history_$department_name_folder/$ticket_id/$key/retirement")) {
       mkdir("../ticket_images_history_$department_name_folder/$ticket_id/$key/retirement",0777,true);
       chmod("../ticket_images_history_$department_name_folder/$ticket_id/$key/retirement", 0777);      
    }
    if (!file_exists("../ticket_images_history_$department_name_folder/$ticket_id/$key/retirement/$retirement_id") && !is_dir("../ticket_images_history_$department_name_folder/$ticket_id/$key/retirement/$retirement_id")) {
       mkdir("../ticket_images_history_$department_name_folder/$ticket_id/$key/retirement/$retirement_id",0777,true);
       chmod("../ticket_images_history_$department_name_folder/$ticket_id/$key/retirement/$retirement_id", 0777);      
    } 
}

function createTmpDirectory($key=null,$img=null){
    if (!file_exists("../tmp") && !is_dir("../tmp")) {
       mkdir("../tmp",0777,true);
       chmod("../tmp", 0777);      
    }
    if (!file_exists("../tmp/$key") && !is_dir("../tmp/$key")) {
       mkdir("../tmp/$key",0777,true);
       chmod("../tmp/$key", 0777);        
    }
    if (!file_exists("../tmp/$key/$img[3]") && !is_dir("../tmp/$key/$img[3]")) {
       mkdir("../tmp/$key/$img[3]",0777,true);
       chmod("../tmp/$key/$img[3]", 0777);      
    }
    if (!file_exists("../tmp/$key/$img[3]/$img[4]") && !is_dir("../tmp/$key/$img[3]/$img[4]")) {
       mkdir("../tmp/$key/$img[3]/$img[4]",0777,true);
       chmod("../tmp/$key/$img[3]/$img[4]", 0777);      
    }
 
}

function get_old_images($ticket_id){
    $qres = hesk_dbQuery("SELECT * FROM `".hesk_dbEscape($hesk_settings['db_pfix'])."hesk_ticket_images` WHERE `ticket_id`='{$ticket_id}' LIMIT 1");
    return $res = hesk_dbFetchAssoc($qres);
}

 function moveFileToDirectory($url=null,$key=null,$img=null,$ticket_id=null,$retirement_id=null,$department_name){
    $department_name_folder = strtolower($department_name);
    $directory = (is_null($ticket_id) ? "../ticket_images_$department_name_folder" : "../ticket_images_$department_name_folder");
    //Save images into directories
    $getFile = $url;
    if($key=='officer_signature'){
        $path = "$directory/$key/$img[5]";
    }
    // else if($key=='passport_size_photos'){
    //     $path = "$directory/$key/retirement/$retirement_id/$img[6]";
    // }
    else{
        $path = "$directory/$key/retirement/$retirement_id/$img[7]";    
    }
    
    $fp = fopen($path, 'w');
    $ch = curl_init($getFile);
    curl_setopt($ch, CURLOPT_FILE, $fp);
    curl_setopt($ch, CURLOPT_RETURNTRANSFER, 1);
    curl_setopt($ch, CURLOPT_FOLLOWLOCATION, 1);
    curl_setopt($ch, CURLOPT_COOKIEJAR, 'cookies');
    curl_setopt($ch, CURLOPT_COOKIEFILE, 'cookies');
    $data = curl_exec($ch);
    fwrite($fp,$data);
    curl_close($ch);
    fclose($fp);  
    return true;
}

function getImage($key=null,$val=null,$officer_id=null,$retirement_id=null,$department_name){
        
      if(!empty($val)){
        foreach($val as $k=>$v){
            $img = explode('/',$v);
            $qres = hesk_dbQuery("SELECT * FROM `".hesk_dbEscape($hesk_settings['db_pfix'])."hesk_ticket_images` WHERE `officer_id`='{$officer_id}' AND department='".$department_name."' and `penrabbit_id_fk` = 0 LIMIT 1");
            $res = hesk_dbFetchAssoc($qres);
            createDirectory($key,$img,$retirement_id,$department_name);
            if(empty($res)){
                //add new user here
                $date = date("Y-m-d H:i:s");
                hesk_dbQuery("INSERT INTO ".hesk_dbEscape($hesk_settings['db_pfix'])."`hesk_ticket_images`
                                (officer_id,retirement_id,department,$key,`status`,created_at)
                                VALUES 
                                (" . hesk_dbEscape($officer_id) . ",
                                " . hesk_dbEscape($retirement_id) . ",'".$department_name."',
                                    '$img[7]',
                                ".  hesk_dbEscape(1) . ",
                                    '$date'
                )");
                
                moveFileToDirectory($v,$key,$img,'',$retirement_id,$department_name);

            }
                // else if(strpos($res[$key],$img[5]) === FALSE){
            else{
               //update record here
               if($res[$key] != '' ){
                  $new_val = "CONCAT($key,$img[7])";
                  hesk_dbQuery("UPDATE `".hesk_dbEscape($hesk_settings['db_pfix'])."hesk_ticket_images` SET $key = CONCAT($key,',".$img[7]."') WHERE `officer_id`=".hesk_dbEscape($officer_id)." AND department='".$department_name."' and `penrabbit_id_fk` = 0 ");
                  //createDirectory($key,$img);
                  moveFileToDirectory($v,$key,$img,$get_duplicate_data['ticket_id'],$retirement_id,$department_name);
               }else{
                  hesk_dbQuery("UPDATE `".hesk_dbEscape($hesk_settings['db_pfix'])."hesk_ticket_images` SET $key = '$img[7]' WHERE `officer_id`=".hesk_dbEscape($officer_id)." AND department='".$department_name."' and `penrabbit_id_fk` = 0");
                  //createDirectory($key,$img);
                  moveFileToDirectory($v,$key,$img,$get_duplicate_data['ticket_id'],$retirement_id,$department_name);
               }
            }
        }
        return true;
      }else{
         return false;
      }  
}

function processImagesFromQue($data,$department_name){
   foreach($data as $key => $val){
  
      if($key == 'officer_id'){
         $officer_id = $val;
      }
      if($key == 'retirement_id'){
         $retirement_id = $val;
      }    
       switch ($key) {
            case "retirement_pdf":
                getImage($key, $val, $officer_id, $retirement_id,$department_name);
            break;
            case "pension_pdf":
                getImage($key, $val, $officer_id, $retirement_id,$department_name);
            break;
            case "annex_a":
                getImage($key,$val,$officer_id,$retirement_id,$department_name);
            break;
            case "annex_b":
                getImage($key,$val,$officer_id,$retirement_id,$department_name);
            break;
            case "service_statement":
                getImage($key,$val,$officer_id,$retirement_id,$department_name);
            break;
            case "no_demand_certificate_building":
                getImage($key,$val,$officer_id,$retirement_id,$department_name);
            break;           
            case "affidavit":
                getImage($key,$val,$officer_id,$retirement_id,$department_name);
            break;           
            case "service_book":
                getImage($key,$val,$officer_id,$retirement_id,$department_name);
            break;   
            case "forwarding_letter_ddo":
                getImage($key,$val,$officer_id,$retirement_id,$department_name);
            break;           
            case "attested_cnic_ddo":
                getImage($key,$val,$officer_id,$retirement_id,$department_name);
            break;           
            case "passport_size_photos":
                getImage($key,$val,$officer_id,$retirement_id,$department_name);
            break;   
            case "pension_sanctioned_form":
                getImage($key,$val,$officer_id,$retirement_id,$department_name);
            break;           
            case "familymember_verified_psa":
                getImage($key,$val,$officer_id,$retirement_id,$department_name);
            break;           
            case "frc_familyregistration":
               getImage($key,$val,$officer_id,$retirement_id,$department_name);
            break;
            case "last_paymentcertificate":
               getImage($key,$val,$officer_id,$retirement_id,$department_name);
            break;
            case "bank_optionform":
               getImage($key,$val,$officer_id,$retirement_id,$department_name);
            break;
            case "indemnity_bond":
               getImage($key,$val,$officer_id,$retirement_id,$department_name);
            break;
            case "last_computirzedpayslip":
               getImage($key,$val,$officer_id,$retirement_id,$department_name);
            break;
            case "retirment_letter":
               getImage($key,$val,$officer_id,$retirement_id,$department_name);
            break;
            case "medical_certificate":
               getImage($key,$val,$officer_id,$retirement_id,$department_name);
            break;
            case "nomarriage_certificate":
               getImage($key,$val,$officer_id,$retirement_id,$department_name);
            break;
            case "lawful_widow_certificate":
               getImage($key,$val,$officer_id,$retirement_id,$department_name);
            break;
            case "incomecertificate_signedbypsa":
               getImage($key,$val,$officer_id,$retirement_id,$department_name);
            break;
            case "reason_for_latesubmission":
               getImage($key,$val,$officer_id,$retirement_id,$department_name);
            break;
            case "computrized_deathcertificate":
               getImage($key,$val,$officer_id,$retirement_id,$department_name);
            break;
            case "computrized_divorcecertification":
               getImage($key,$val,$officer_id,$retirement_id,$department_name);
            break;
            case "computrized_marriageregistration":
               getImage($key,$val,$officer_id,$retirement_id,$department_name);
            break;
            case "officer_signature":
               getImage($key,$val,$officer_id,$retirement_id,$department_name);
            break;
            case "other_attachment":
                getImage($key,$val,$officer_id,$retirement_id,$department_name);
            break;
           
       } 
    }
}

function check_duplicate($officer_id,$department_name){
    $qres = hesk_dbQuery("SELECT * FROM `".hesk_dbEscape($hesk_settings['db_pfix'])."hesk_ticket_images` WHERE `officer_id`='{$officer_id}' and department='".$department_name."' and `penrabbit_id_fk` > 0 LIMIT 1");
    return $res = hesk_dbFetchAssoc($qres);
}

function check_duplicate_rabbit_user($officer_id,$department_name){
    $qres = hesk_dbQuery("SELECT * FROM `".hesk_dbEscape($hesk_settings['db_pfix'])."hesk_ag_penrabbitmq` WHERE `officer_id`='{$officer_id}' and department='".$department_name."' and `ticket_id` = 0 LIMIT 1");
    return $res = hesk_dbFetchAssoc($qres);
}

$listener->pull($listenQueue, $permanent, $listenTag, function ($message) {
    try {
        $dinfo = $message->delivery_info;
        $pull_status = 'ACK';
        $pull_datetime = date('Y-m-d H:i:s');
        $listenQueue = 'FIRBKP';

        $res = json_decode($message->body,true);
        $tmp_res = $res;
        $officer_id = $res['officer_id'];
        $retirement_id = $res['retirement_id'];
        $department_name = $res['department'];
        $department_name_folder = strtolower($department_name);;
        unset($tmp_res['officer_id']);
        unset($tmp_res['retirement_id']);
        unset($tmp_res['district']);
        unset($tmp_res['department']);
        unset($tmp_res['firstname']);
        unset($tmp_res['personal_no']);
        unset($tmp_res['cnic']);
        unset($tmp_res['opr_phone']);
		unset($tmp_res['so_comments']);
		
		if(isset($res['system']) && $res['system']!=''){
            $system = $res['system'];
            unset($tmp_res['system']);
        } else{
            $system = '';
        } 
       
        $check_rabbit_duplicate = check_duplicate_rabbit_user($res['officer_id'],$department_name);
        $get_duplicate_data = check_duplicate($res['officer_id'],$department_name);
		
        if(empty($check_rabbit_duplicate)){
            $ticket_id = $get_duplicate_data['ticket_id'];
            if($ticket_id > 0){
                foreach($tmp_res as $key => $vall){
                    if(!empty($vall)){
						foreach($vall as $v){
							$img = explode('/',$v);
							createHistoryDirectory($ticket_id,$key,$img,$retirement_id,$department_name);
							$files = scandir("../ticket_images_$department_name_folder/$key/retirement/$retirement_id/");
							$source_folder = "../ticket_images_$department_name_folder/$key/retirement/$retirement_id/";    
							$destination_folder = "../ticket_images_history_$department_name_folder/$ticket_id/$key/retirement/$retirement_id/";
							foreach($files as $fname) {
								if($fname != '.' && $fname != '..') {
									rename($source_folder.$fname, $destination_folder.$fname);
									
								}
							} 
						}
						
                    }
                    
                }
            }
			 hesk_dbQuery("INSERT INTO `hesk_ag_penrabbitmq`
            (`listened_data`,`cnic`, `firstname`, `officer_id`, `opr_phone`, `personal_no`, `retirement_id`, `district`, `department`,`so_comments`,`system`)
            VALUES 
            ('" . hesk_dbEscape($message->body) . "','" . hesk_dbEscape($res['cnic']) . "','" . hesk_dbEscape($res['firstname']) . "','" . hesk_dbEscape($res['officer_id']) . "','" . hesk_dbEscape($res['opr_phone']) . "','" . hesk_dbEscape($res['personal_no']) . "','" . hesk_dbEscape($res['retirement_id']) . "','" . hesk_dbEscape($res['district']) . "','" . hesk_dbEscape($res['department']) . "','" . hesk_dbEscape($res['so_comments']) . "','" . hesk_dbEscape($system) . "')");
            processImagesFromQue($res,$department_name);
        }
        

        echo $message->body . ' ------------- ' . $message->delivery_info['exchange'] . ' -------- ' . $message->delivery_info['routing_key'] . '<br/>';
        $message->delivery_info['channel']->basic_ack($message->delivery_info['delivery_tag']);
        
    } catch (Exception $e) {
        $pull_status = 'NACK';
        $message->delivery_info['channel']->basic_nack($message->delivery_info['delivery_tag']);
    }
});

